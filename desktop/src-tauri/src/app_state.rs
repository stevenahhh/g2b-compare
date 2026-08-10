use std::{
    fs::{self, OpenOptions},
    io::{self, ErrorKind, Write},
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};

use serde::{Deserialize, Serialize};
use tauri::{Manager, State, WebviewWindow};
use thiserror::Error;

use crate::{
    db::{Migration, MigrationError, apply_migrations},
    estimate::{
        CANONICAL_QUANTITY, CreateEstimate, EstimateComparisonInput, EstimateDocument,
        EstimateError, EstimateLine, EstimateLineInput, EstimateRepository, UpdateEstimate,
        events::{EstimateChangeEvent, EstimateChangeKind, emit_estimate_change},
    },
    export_workbook::{
        ComparisonSlot, ExportComparison, ExportLine, ExportWorkbookError, TemplateAssets,
        WorkbookDraft, export_workbook,
    },
    offline_replay::{
        ConflictResolution, Mutation, ReconciliationEvent, ReplayDecision, ReplayError,
        ReplayStore, ReplayTarget,
    },
};

const TEMPLATE_FILE_NAME: &str = "estimate-template-v1.xlsx";
const TEMPLATE_MANIFEST_FILE_NAME: &str = "estimate-template-v1.json";
const FALLBACK_IMAGE_FILE_NAME: &str = "estimate-no-image.png";
const CLIPBOARD_COLUMN_COUNT: usize = 17;
const CLIPBOARD_HEADER: &str = "품명\t규격\t단위\t적용단가\t적용회사\t규격\t물품식별번호\t단가\t회사명\t규격\t물품식별번호\t단가\t회사명\t규격\t물품식별번호\t단가\t비고\n";
const COMPARISON_SLOTS: [&str; 3] = ["A", "B", "C"];
const MAX_EXPORT_PATH_ATTEMPTS: u16 = 1_000;
const MAX_EXPORT_TITLE_CHARACTERS: usize = 100;
const DESKTOP_VIEW_MIGRATIONS: [Migration; 1] = [Migration::new(
    "0001_initial",
    "
CREATE TABLE IF NOT EXISTS desktop_view_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    route TEXT NOT NULL,
    path TEXT NOT NULL
);
",
)];

const EMBEDDED_ESTIMATE_TEMPLATE: &[u8] =
    include_bytes!("../../../src/g2b_compare/assets/estimate-template-v1.xlsx");
const EMBEDDED_TEMPLATE_MANIFEST: &[u8] =
    include_bytes!("../../../src/g2b_compare/assets/estimate-template-v1.json");
const EMBEDDED_FALLBACK_IMAGE: &[u8] =
    include_bytes!("../../../src/g2b_compare/assets/estimate-no-image.png");

/// The visible top-level desktop route persisted between launches.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DesktopRoute {
    Catalog,
    Estimates,
    Estimate,
    Data,
}

/// The exact durable shell state consumed by the desktop frontend.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DesktopViewState {
    pub route: DesktopRoute,
    pub path: String,
}

/// The exact result returned after a workbook has been atomically published.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct WorkbookExportResult {
    pub path: String,
    pub file_name: String,
}

/// The exact result returned after a TSV table has crossed the native clipboard boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct ClipboardCopyResult {
    pub row_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ClipboardRow {
    item_name: String,
    specification: String,
    unit: String,
    applied_price_won: String,
    comparisons: [ClipboardComparison; 3],
    note: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct ClipboardComparison {
    company: String,
    specification: String,
    product_id: String,
    price_won: String,
}

/// The frontend-visible reconciliation state.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconciliationState {
    Idle,
    Offline,
    Queued,
    Replaying,
    Conflict,
}

/// One durable remote reconciliation conflict that requires a user decision.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ReconciliationConflict {
    pub sequence: u64,
    pub entity_id: String,
    pub reason_code: String,
}

/// The complete reconciliation view consumed by the offline banner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ReconciliationStatus {
    pub state: ReconciliationState,
    pub online: bool,
    pub queued_count: u64,
    pub conflicts: Vec<ReconciliationConflict>,
}

/// The renderer-supplied resolution request for one durable conflict.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
pub struct ResolveReconciliationConflictRequest {
    pub sequence: u64,
    pub resolution: ReconciliationResolution,
}

/// The only conflict outcomes available to the renderer.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "kebab-case")]
pub enum ReconciliationResolution {
    KeepLocal,
    UseRemote,
}

impl From<ReconciliationResolution> for ConflictResolution {
    fn from(value: ReconciliationResolution) -> Self {
        match value {
            ReconciliationResolution::KeepLocal => Self::KeepLocal,
            ReconciliationResolution::UseRemote => Self::UseRemote,
        }
    }
}

#[derive(Debug, Error)]
pub enum AppStateError {
    #[error(transparent)]
    Estimate(#[from] EstimateError),
    #[error(transparent)]
    Export(#[from] ExportWorkbookError),
    #[error(transparent)]
    Replay(#[from] ReplayError),
    #[error("desktop view path has no parent directory")]
    ViewPathMissingParent,
    #[error("desktop view is invalid: {0}")]
    InvalidView(&'static str),
    #[error("desktop view I/O failed: {0}")]
    ViewIo(#[source] io::Error),
    #[error(transparent)]
    ViewMigration(#[from] MigrationError),
    #[error("desktop view database operation failed: {0}")]
    ViewSqlite(#[source] rusqlite::Error),
    #[error("embedded estimate workbook template is invalid or was modified")]
    TemplateIntegrity,
    #[error("embedded estimate workbook template cannot be installed: {0}")]
    TemplateInstall(#[source] io::Error),
    #[error("an estimate must contain at least one line before export")]
    EmptyExport,
    #[error("every exported estimate line requires A, B, and C comparisons")]
    IncompleteComparisons,
    #[error("the export directory cannot be prepared: {0}")]
    ExportDirectoryIo(#[source] io::Error),
    #[error("the selected export directory is not a directory")]
    InvalidExportDirectory,
    #[error("the export directory cannot represent a path returned to the desktop frontend")]
    NonUnicodeExportPath,
    #[error("a unique workbook export name could not be selected")]
    ExportPathExhausted,
    #[error("the native clipboard is unavailable")]
    ClipboardUnavailable,
    #[error("reconciliation replay is already in progress")]
    ReplayInProgress,
    #[error("reconciliation state lock is poisoned")]
    StateLockPoisoned,
}

#[derive(Clone, Debug)]
struct DesktopViewStore {
    path: PathBuf,
}

impl DesktopViewStore {
    fn open(path: PathBuf) -> Result<Self, AppStateError> {
        let parent = path.parent().ok_or(AppStateError::ViewPathMissingParent)?;
        fs::create_dir_all(parent).map_err(AppStateError::ViewIo)?;
        apply_migrations(&path, &DESKTOP_VIEW_MIGRATIONS)?;
        Ok(Self { path })
    }

    fn load(&self) -> Result<Option<DesktopViewState>, AppStateError> {
        use rusqlite::OptionalExtension;

        let view = self
            .connection()?
            .query_row(
                "SELECT route, path FROM desktop_view_state WHERE singleton = 1",
                [],
                |row| {
                    Ok(DesktopViewState {
                        route: route_from_storage(&row.get::<_, String>(0)?)?,
                        path: row.get(1)?,
                    })
                },
            )
            .optional()
            .map_err(AppStateError::ViewSqlite)?;
        if let Some(view) = &view {
            validate_view(view)?;
        }
        Ok(view)
    }

    fn save(&self, view: &DesktopViewState) -> Result<(), AppStateError> {
        validate_view(view)?;
        self.connection()?
            .execute(
                "INSERT INTO desktop_view_state (singleton, route, path)
                 VALUES (1, ?1, ?2)
                 ON CONFLICT(singleton) DO UPDATE SET
                     route = excluded.route,
                     path = excluded.path",
                rusqlite::params![route_for_storage(view.route), &view.path],
            )
            .map_err(AppStateError::ViewSqlite)?;
        Ok(())
    }

    fn connection(&self) -> Result<rusqlite::Connection, AppStateError> {
        let connection =
            rusqlite::Connection::open(&self.path).map_err(AppStateError::ViewSqlite)?;
        connection
            .busy_timeout(std::time::Duration::from_secs(5))
            .map_err(AppStateError::ViewSqlite)?;
        Ok(connection)
    }
}

struct DesktopService {
    repository: EstimateRepository,
    view_store: DesktopViewStore,
    replay_store: Arc<ReplayStore>,
    template_assets: TemplateAssets,
    export_directory: PathBuf,
    export_lock: Mutex<()>,
    replay_target: Mutex<Box<dyn ReplayTarget + Send>>,
    online: AtomicBool,
    replaying: AtomicBool,
}

/// Managed command state for saved-document actions, shell persistence, and reconciliation.
#[derive(Clone)]
pub struct DesktopState {
    service: Arc<DesktopService>,
}

impl DesktopState {
    /// Creates the managed state from only application-owned paths and a durable replay queue.
    ///
    /// # Errors
    ///
    /// Returns an error when the estimate repository, view database, or export directory cannot
    /// be opened safely.
    pub fn new(
        database: impl AsRef<Path>,
        view_database: PathBuf,
        replay_store: Arc<ReplayStore>,
        template_assets: TemplateAssets,
        export_directory: PathBuf,
    ) -> Result<Self, AppStateError> {
        fs::create_dir_all(&export_directory).map_err(AppStateError::ExportDirectoryIo)?;
        if !fs::metadata(&export_directory)
            .map_err(AppStateError::ExportDirectoryIo)?
            .is_dir()
        {
            return Err(AppStateError::InvalidExportDirectory);
        }
        let repository = EstimateRepository::open(database)?;
        Ok(Self {
            service: Arc::new(DesktopService {
                repository: repository.clone(),
                view_store: DesktopViewStore::open(view_database)?,
                replay_store,
                template_assets,
                export_directory,
                export_lock: Mutex::new(()),
                replay_target: Mutex::new(Box::new(EstimateReplayTarget::new(repository))),
                online: AtomicBool::new(true),
                replaying: AtomicBool::new(false),
            }),
        })
    }

    #[cfg(test)]
    fn with_replay_target(
        self,
        replay_target: Box<dyn ReplayTarget + Send>,
    ) -> Result<Self, AppStateError> {
        let mut target = self
            .service
            .replay_target
            .lock()
            .map_err(|_error| AppStateError::StateLockPoisoned)?;
        *target = replay_target;
        drop(target);
        Ok(self)
    }
}

const REVISION_CONFLICT_REASON: &str = "remote-revision-conflict";
const UNSUPPORTED_MUTATION_REASON: &str = "payload is not a supported estimate command";

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum PersistedEstimateMutation {
    #[serde(rename = "create_estimate")]
    Create { request: CreateEstimate },
    #[serde(rename = "update_estimate")]
    Update { id: String, request: UpdateEstimate },
    #[serde(rename = "delete_estimate")]
    Delete { id: String },
}

struct EstimateReplayTarget {
    repository: EstimateRepository,
}

impl EstimateReplayTarget {
    const fn new(repository: EstimateRepository) -> Self {
        Self { repository }
    }

    fn parse(mutation: &Mutation) -> Result<PersistedEstimateMutation, ReplayError> {
        let payload = serde_json::from_slice::<PersistedEstimateMutation>(&mutation.payload)
            .map_err(|_error| ReplayError::MalformedPayload {
                sequence: mutation.sequence,
                reason: UNSUPPORTED_MUTATION_REASON.to_owned(),
            })?;
        let entity_id = match &payload {
            PersistedEstimateMutation::Create { request } => &request.id,
            PersistedEstimateMutation::Update { id, .. }
            | PersistedEstimateMutation::Delete { id } => id,
        };
        if entity_id != &mutation.entity_id {
            return Err(ReplayError::MalformedPayload {
                sequence: mutation.sequence,
                reason: UNSUPPORTED_MUTATION_REASON.to_owned(),
            });
        }
        Ok(payload)
    }

    fn apply_create(
        &self,
        mutation: &Mutation,
        request: &CreateEstimate,
    ) -> Result<ReplayDecision, ReplayError> {
        match self.repository.read(&request.id) {
            Ok(document) => Ok(create_decision(&document, request)),
            Err(EstimateError::NotFound { .. }) => match self.repository.create(request.clone()) {
                Ok(_) => Ok(ReplayDecision::Applied),
                Err(EstimateError::Constraint { .. }) => {
                    self.read_create_decision(mutation, request)
                }
                Err(_) => Err(apply_failure(mutation.sequence)),
            },
            Err(_) => Err(apply_failure(mutation.sequence)),
        }
    }

    fn read_create_decision(
        &self,
        mutation: &Mutation,
        request: &CreateEstimate,
    ) -> Result<ReplayDecision, ReplayError> {
        self.repository.read(&request.id).map_or_else(
            |_error| Err(apply_failure(mutation.sequence)),
            |document| Ok(create_decision(&document, request)),
        )
    }

    fn apply_update(
        &self,
        mutation: &Mutation,
        id: &str,
        request: &UpdateEstimate,
    ) -> Result<ReplayDecision, ReplayError> {
        match self.repository.update(id, request.clone()) {
            Ok(_) => Ok(ReplayDecision::Applied),
            Err(EstimateError::RevisionConflict { .. }) => match self.repository.read(id) {
                Ok(document) if document_matches_update(&document, request) => {
                    Ok(ReplayDecision::Applied)
                }
                Ok(_) | Err(EstimateError::NotFound { .. }) => Ok(ReplayDecision::Conflict {
                    reason: REVISION_CONFLICT_REASON.to_owned(),
                }),
                Err(_) => Err(apply_failure(mutation.sequence)),
            },
            Err(EstimateError::NotFound { .. }) => Ok(ReplayDecision::Conflict {
                reason: REVISION_CONFLICT_REASON.to_owned(),
            }),
            Err(_) => Err(apply_failure(mutation.sequence)),
        }
    }

    fn apply_delete(&self, mutation: &Mutation, id: &str) -> Result<ReplayDecision, ReplayError> {
        match self.repository.delete(id) {
            Ok(()) | Err(EstimateError::NotFound { .. }) => Ok(ReplayDecision::Applied),
            Err(_) => Err(apply_failure(mutation.sequence)),
        }
    }
}

impl ReplayTarget for EstimateReplayTarget {
    fn apply(&mut self, mutation: &Mutation) -> Result<ReplayDecision, ReplayError> {
        match Self::parse(mutation)? {
            PersistedEstimateMutation::Create { request } => self.apply_create(mutation, &request),
            PersistedEstimateMutation::Update { id, request } => {
                self.apply_update(mutation, &id, &request)
            }
            PersistedEstimateMutation::Delete { id } => self.apply_delete(mutation, &id),
        }
    }
}

fn apply_failure(sequence: u64) -> ReplayError {
    ReplayError::Transport(format!("estimate mutation {sequence} could not be applied"))
}

fn create_decision(document: &EstimateDocument, request: &CreateEstimate) -> ReplayDecision {
    if document.revision == 1
        && document.id == request.id
        && document.template_sha256 == request.template_sha256
        && document_matches_contents(
            document,
            &request.title,
            &request.lines,
            &request.comparisons,
        )
    {
        ReplayDecision::Applied
    } else {
        ReplayDecision::Conflict {
            reason: REVISION_CONFLICT_REASON.to_owned(),
        }
    }
}

fn document_matches_update(document: &EstimateDocument, request: &UpdateEstimate) -> bool {
    request
        .expected_revision
        .checked_add(1)
        .is_some_and(|revision| document.revision == revision)
        && document_matches_contents(
            document,
            &request.title,
            &request.lines,
            &request.comparisons,
        )
}

fn document_matches_contents(
    document: &EstimateDocument,
    title: &str,
    lines: &[EstimateLineInput],
    comparisons: &[EstimateComparisonInput],
) -> bool {
    document.title == title
        && lines_match(&document.lines, lines)
        && comparison_snapshots(document) == input_comparison_snapshots(comparisons)
}

fn lines_match(saved: &[EstimateLine], input: &[EstimateLineInput]) -> bool {
    saved.len() == input.len()
        && saved
            .iter()
            .zip(input)
            .enumerate()
            .all(|(index, (saved, input))| {
                let Some(line_no) = index
                    .checked_add(1)
                    .and_then(|value| i64::try_from(value).ok())
                else {
                    return false;
                };
                saved.line_no == line_no
                    && saved.id == input.id
                    && saved.line_kind == input.line_kind
                    && saved.product_id == input.product_id
                    && saved.parent_product_id == input.parent_product_id
                    && saved.relation_id == input.relation_id
                    && saved.offer_operation == input.offer_operation
                    && saved.offer_key == input.offer_key
                    && saved.item_name_snapshot == input.item_name_snapshot
                    && saved.spec_snapshot == input.spec_snapshot
                    && saved.company_snapshot == input.company_snapshot
                    && saved.unit_snapshot == input.unit_snapshot
                    && saved.unit_price_won_snapshot == input.unit_price_won_snapshot
                    && quantities_match(&saved.quantity, &input.quantity)
            })
}

fn quantities_match(saved: &str, input: &str) -> bool {
    saved == CANONICAL_QUANTITY && input == CANONICAL_QUANTITY
}

#[derive(Eq, Ord, PartialEq, PartialOrd)]
struct ComparisonSnapshot {
    estimate_line_id: String,
    slot: String,
    product_id: String,
    relation_id: Option<String>,
    company_snapshot: String,
    spec_snapshot: String,
    price_won_snapshot: i64,
}

fn comparison_snapshots(document: &EstimateDocument) -> Vec<ComparisonSnapshot> {
    let mut snapshots = document
        .lines
        .iter()
        .flat_map(|line| line.comparisons.iter())
        .map(|comparison| ComparisonSnapshot {
            estimate_line_id: comparison.estimate_line_id.clone(),
            slot: comparison.slot.clone(),
            product_id: comparison.product_id.clone(),
            relation_id: comparison.relation_id.clone(),
            company_snapshot: comparison.company_snapshot.clone(),
            spec_snapshot: comparison.spec_snapshot.clone(),
            price_won_snapshot: comparison.price_won_snapshot,
        })
        .collect::<Vec<_>>();
    snapshots.sort_unstable();
    snapshots
}

fn input_comparison_snapshots(input: &[EstimateComparisonInput]) -> Vec<ComparisonSnapshot> {
    let mut snapshots = input
        .iter()
        .map(|comparison| ComparisonSnapshot {
            estimate_line_id: comparison.estimate_line_id.clone(),
            slot: comparison.slot.clone(),
            product_id: comparison.product_id.clone(),
            relation_id: comparison.relation_id.clone(),
            company_snapshot: comparison.company_snapshot.clone(),
            spec_snapshot: comparison.spec_snapshot.clone(),
            price_won_snapshot: comparison.price_won_snapshot,
        })
        .collect::<Vec<_>>();
    snapshots.sort_unstable();
    snapshots
}

trait ClipboardWriter {
    fn write_tsv(&mut self, value: &str) -> Result<(), AppStateError>;
}

struct SystemClipboard {
    #[cfg(target_os = "windows")]
    clipboard: arboard::Clipboard,
}

impl SystemClipboard {
    fn new() -> Result<Self, AppStateError> {
        #[cfg(target_os = "windows")]
        {
            arboard::Clipboard::new()
                .map(|clipboard| Self { clipboard })
                .map_err(|_error| AppStateError::ClipboardUnavailable)
        }
        #[cfg(not(target_os = "windows"))]
        {
            Err(AppStateError::ClipboardUnavailable)
        }
    }
}

impl ClipboardWriter for SystemClipboard {
    fn write_tsv(&mut self, value: &str) -> Result<(), AppStateError> {
        #[cfg(target_os = "windows")]
        {
            self.clipboard
                .set_text(value)
                .map_err(|_error| AppStateError::ClipboardUnavailable)
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _value = value;
            Err(AppStateError::ClipboardUnavailable)
        }
    }
}

/// Installs the immutable workbook, manifest, and fallback image under application data.
///
/// Each asset is created once without replacing an existing file. Existing assets must match the
/// compile-time bytes exactly, so a damaged local package fails before an export is attempted.
///
/// # Errors
///
/// Returns an error when the application directory cannot safely hold the immutable assets.
pub fn install_embedded_estimate_assets(app_data: &Path) -> Result<TemplateAssets, AppStateError> {
    let template_directory = app_data.join("templates");
    fs::create_dir_all(&template_directory).map_err(AppStateError::TemplateInstall)?;
    Ok(TemplateAssets::new(
        install_embedded_asset(
            &template_directory,
            TEMPLATE_FILE_NAME,
            EMBEDDED_ESTIMATE_TEMPLATE,
        )?,
        install_embedded_asset(
            &template_directory,
            TEMPLATE_MANIFEST_FILE_NAME,
            EMBEDDED_TEMPLATE_MANIFEST,
        )?,
        install_embedded_asset(
            &template_directory,
            FALLBACK_IMAGE_FILE_NAME,
            EMBEDDED_FALLBACK_IMAGE,
        )?,
    ))
}

fn install_embedded_asset(
    directory: &Path,
    file_name: &str,
    contents: &[u8],
) -> Result<PathBuf, AppStateError> {
    let destination = directory.join(file_name);
    match fs::read(&destination) {
        Ok(existing) if existing == contents => return Ok(destination),
        Ok(_) => return Err(AppStateError::TemplateIntegrity),
        Err(error) if error.kind() != ErrorKind::NotFound => {
            return Err(AppStateError::TemplateInstall(error));
        }
        Err(_) => {}
    }

    let temporary = directory.join(format!("{file_name}.{}.tmp", std::process::id()));
    write_asset_temporary(&temporary, contents)?;
    match fs::hard_link(&temporary, &destination) {
        Ok(()) => fs::remove_file(&temporary).map_err(AppStateError::TemplateInstall)?,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            fs::remove_file(&temporary).map_err(AppStateError::TemplateInstall)?;
            let existing = fs::read(&destination).map_err(AppStateError::TemplateInstall)?;
            if existing != contents {
                return Err(AppStateError::TemplateIntegrity);
            }
        }
        Err(error) => {
            remove_asset_temporary(&temporary)?;
            return Err(AppStateError::TemplateInstall(error));
        }
    }
    Ok(destination)
}

fn write_asset_temporary(path: &Path, contents: &[u8]) -> Result<(), AppStateError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(AppStateError::TemplateInstall)?;
    let result = file.write_all(contents).and_then(|()| file.sync_all());
    drop(file);
    match result {
        Ok(()) => Ok(()),
        Err(error) => {
            remove_asset_temporary(path)?;
            Err(AppStateError::TemplateInstall(error))
        }
    }
}

fn remove_asset_temporary(path: &Path) -> Result<(), AppStateError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(AppStateError::TemplateInstall(error)),
    }
}

/// Exports one saved, complete estimate through the fixed exporter into a safe application path.
///
/// # Errors
///
/// Returns a displayable error when the saved document is missing or incomplete, the output path
/// cannot be selected, or the exporter does not atomically publish the workbook.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn export_estimate_workbook(
    state: State<'_, DesktopState>,
    id: String,
) -> Result<WorkbookExportResult, String> {
    export_estimate_workbook_inner(&state, &id).map_err(command_error)
}

/// Copies the exact permitted TSV projection of a saved estimate through the native clipboard.
///
/// This is the only command that constructs the real platform clipboard. The renderer receives
/// only the row count, never the TSV or a generic clipboard capability.
///
/// # Errors
///
/// Returns a displayable error when the saved estimate cannot be read or the native clipboard is
/// unavailable.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn copy_estimate_table(
    state: State<'_, DesktopState>,
    id: String,
) -> Result<ClipboardCopyResult, String> {
    let mut clipboard = SystemClipboard::new().map_err(command_error)?;
    copy_estimate_table_inner(&state, &id, &mut clipboard).map_err(command_error)
}

/// Loads the durable top-level desktop view, if one has been saved.
///
/// # Errors
///
/// Returns a displayable error when the durable state cannot be read or is invalid.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn load_desktop_view(
    state: State<'_, DesktopState>,
) -> Result<Option<DesktopViewState>, String> {
    state.service.view_store.load().map_err(command_error)
}

/// Saves the exact top-level desktop view state.
///
/// # Errors
///
/// Returns a displayable error when the renderer supplies an invalid route/path pair or durable
/// storage rejects the update.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn save_desktop_view(
    desktop_state: State<'_, DesktopState>,
    state: DesktopViewState,
) -> Result<(), String> {
    desktop_state
        .service
        .view_store
        .save(&state)
        .map_err(command_error)
}

/// Returns the current durable replay queue and every persisted unresolved conflict.
///
/// # Errors
///
/// Returns a displayable error when the replay queue cannot be read safely.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn get_reconciliation_status(
    state: State<'_, DesktopState>,
) -> Result<ReconciliationStatus, String> {
    reconciliation_status_inner(&state).map_err(command_error)
}

/// Attempts replay using the configured native reconciliation target.
///
/// Applied mutations are removed by the durable replay store. Conflicts remain queued and are
/// returned by the status result. Target failures return an error and leave all unacknowledged
/// work durable.
///
/// # Errors
///
/// Returns a displayable, credential-safe error when replay cannot complete.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn replay_pending_changes(
    state: State<'_, DesktopState>,
    source: WebviewWindow,
) -> Result<ReconciliationStatus, String> {
    let (status, changes) =
        replay_pending_changes_with_changes_inner(&state).map_err(replay_command_error)?;
    for change in changes {
        emit_estimate_change(source.app_handle(), change).map_err(command_error)?;
    }
    Ok(status)
}

/// Resolves a durable replay conflict by retaining it for another local attempt or discarding it.
///
/// # Errors
///
/// Returns a displayable error when the requested durable conflict no longer exists.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn resolve_reconciliation_conflict(
    state: State<'_, DesktopState>,
    request: ResolveReconciliationConflictRequest,
) -> Result<ReconciliationStatus, String> {
    resolve_reconciliation_conflict_inner(&state, &request).map_err(command_error)
}

fn export_estimate_workbook_inner(
    state: &DesktopState,
    id: &str,
) -> Result<WorkbookExportResult, AppStateError> {
    let _export_guard = state
        .service
        .export_lock
        .lock()
        .map_err(|_error| AppStateError::StateLockPoisoned)?;
    let document = state.service.repository.read(id)?;
    let draft = workbook_draft(&document)?;
    let base_name = export_base_name(&document.title);

    for attempt in 0..MAX_EXPORT_PATH_ATTEMPTS {
        let file_name = export_file_name(&base_name, attempt);
        let destination = state.service.export_directory.join(&file_name);
        match export_workbook(&state.service.template_assets, &destination, &draft) {
            Ok(()) => {
                let path = destination
                    .to_str()
                    .ok_or(AppStateError::NonUnicodeExportPath)?
                    .to_owned();
                return Ok(WorkbookExportResult { path, file_name });
            }
            Err(ExportWorkbookError::DestinationExists { .. }) => {}
            Err(error) => return Err(error.into()),
        }
    }
    Err(AppStateError::ExportPathExhausted)
}

fn copy_estimate_table_inner(
    state: &DesktopState,
    id: &str,
    clipboard: &mut dyn ClipboardWriter,
) -> Result<ClipboardCopyResult, AppStateError> {
    let document = state.service.repository.read(id)?;
    let rows = clipboard_rows(&document);
    let row_count =
        u64::try_from(rows.len()).map_err(|_error| AppStateError::ClipboardUnavailable)?;
    let tsv = format_clipboard(&rows);
    clipboard.write_tsv(&tsv)?;
    Ok(ClipboardCopyResult { row_count })
}

fn reconciliation_status_inner(
    state: &DesktopState,
) -> Result<ReconciliationStatus, AppStateError> {
    let queued = state.service.replay_store.pending()?;
    let conflicts = state
        .service
        .replay_store
        .conflicts()?
        .into_iter()
        .map(|conflict| ReconciliationConflict {
            sequence: conflict.sequence,
            entity_id: conflict.entity_id,
            reason_code: conflict.reason_code,
        })
        .collect::<Vec<_>>();
    let queued_count = u64::try_from(queued.len())
        .map_err(|_error| AppStateError::Replay(ReplayError::StatePoisoned))?;
    let online = state.service.online.load(Ordering::Acquire);
    let state = if !conflicts.is_empty() {
        ReconciliationState::Conflict
    } else if state.service.replaying.load(Ordering::Acquire) {
        ReconciliationState::Replaying
    } else if queued_count > 0 && online {
        ReconciliationState::Queued
    } else if queued_count > 0 || !online {
        ReconciliationState::Offline
    } else {
        ReconciliationState::Idle
    };
    Ok(ReconciliationStatus {
        state,
        online,
        queued_count,
        conflicts,
    })
}

#[cfg(test)]
fn replay_pending_changes_inner(
    state: &DesktopState,
) -> Result<ReconciliationStatus, AppStateError> {
    replay_pending_changes_with_changes_inner(state).map(|(status, _changes)| status)
}

fn replay_pending_changes_with_changes_inner(
    state: &DesktopState,
) -> Result<(ReconciliationStatus, Vec<EstimateChangeEvent>), AppStateError> {
    if state.service.replaying.swap(true, Ordering::AcqRel) {
        return Err(AppStateError::ReplayInProgress);
    }
    let reset = ReplayFlag::new(&state.service.replaying);
    let materializations = replay_materializations(&state.service.replay_store.pending()?);
    let mut applied_sequences = Vec::new();
    let mut target = state
        .service
        .replay_target
        .lock()
        .map_err(|_error| AppStateError::StateLockPoisoned)?;
    let result = state.service.replay_store.replay(&mut **target, |event| {
        if let ReconciliationEvent::Applied { sequence, .. } = event {
            applied_sequences.push(sequence);
        }
    });
    drop(target);
    match result {
        Ok(()) => state.service.online.store(true, Ordering::Release),
        Err(ReplayError::Transport(_)) => {
            state.service.online.store(false, Ordering::Release);
            return Err(AppStateError::Replay(ReplayError::Transport(
                "reconciliation replay failed".to_owned(),
            )));
        }
        Err(error) => return Err(AppStateError::Replay(error)),
    }
    drop(reset);
    let changes = materialized_estimate_changes(state, &materializations, &applied_sequences)?;
    Ok((reconciliation_status_inner(state)?, changes))
}

struct ReplayMaterialization {
    sequence: u64,
    id: String,
    kind: EstimateChangeKind,
}

fn replay_materializations(queued: &[Mutation]) -> Vec<ReplayMaterialization> {
    queued
        .iter()
        .filter_map(|mutation| {
            let payload = EstimateReplayTarget::parse(mutation).ok()?;
            let (id, kind) = match payload {
                PersistedEstimateMutation::Create { request } => {
                    (request.id, EstimateChangeKind::Saved)
                }
                PersistedEstimateMutation::Update { id, .. } => (id, EstimateChangeKind::Saved),
                PersistedEstimateMutation::Delete { id } => (id, EstimateChangeKind::Deleted),
            };
            Some(ReplayMaterialization {
                sequence: mutation.sequence,
                id,
                kind,
            })
        })
        .collect()
}

fn materialized_estimate_changes(
    state: &DesktopState,
    materializations: &[ReplayMaterialization],
    applied_sequences: &[u64],
) -> Result<Vec<EstimateChangeEvent>, AppStateError> {
    applied_sequences
        .iter()
        .filter_map(|sequence| {
            materializations
                .iter()
                .find(|materialization| materialization.sequence == *sequence)
        })
        .map(|materialization| match materialization.kind {
            EstimateChangeKind::Saved => state
                .service
                .repository
                .read(&materialization.id)
                .map(|document| EstimateChangeEvent::saved(document.id, document.revision))
                .map_err(AppStateError::Estimate),
            EstimateChangeKind::Deleted => Ok(EstimateChangeEvent::deleted(&materialization.id)),
        })
        .collect()
}

fn resolve_reconciliation_conflict_inner(
    state: &DesktopState,
    request: &ResolveReconciliationConflictRequest,
) -> Result<ReconciliationStatus, AppStateError> {
    state
        .service
        .replay_store
        .resolve_conflict(request.sequence, request.resolution.into())?;
    reconciliation_status_inner(state)
}

struct ReplayFlag<'a> {
    replaying: &'a AtomicBool,
}

impl<'a> ReplayFlag<'a> {
    const fn new(replaying: &'a AtomicBool) -> Self {
        Self { replaying }
    }
}

impl Drop for ReplayFlag<'_> {
    fn drop(&mut self) {
        self.replaying.store(false, Ordering::Release);
    }
}

fn workbook_draft(document: &EstimateDocument) -> Result<WorkbookDraft, AppStateError> {
    if document.lines.is_empty() {
        return Err(AppStateError::EmptyExport);
    }
    let lines = document
        .lines
        .iter()
        .map(|line| {
            let comparisons = line
                .comparisons
                .iter()
                .map(|comparison| {
                    Ok(ExportComparison {
                        slot: comparison_slot(&comparison.slot)?,
                        product_id: comparison.product_id.clone(),
                        company: comparison.company_snapshot.clone(),
                        specification: comparison.spec_snapshot.clone(),
                        price_won: comparison.price_won_snapshot,
                    })
                })
                .collect::<Result<Vec<_>, AppStateError>>()?;
            Ok(ExportLine {
                item_name: line.item_name_snapshot.clone(),
                specification: line.spec_snapshot.clone(),
                unit: line.unit_snapshot.clone(),
                quantity: CANONICAL_QUANTITY.to_owned(),
                line_kind: line.line_kind.clone(),
                parent_product_id: line.parent_product_id.clone(),
                product_id: line.product_id.clone(),
                company: line.company_snapshot.clone(),
                unit_price_won: line.unit_price_won_snapshot,
                comparisons,
            })
        })
        .collect::<Result<Vec<_>, AppStateError>>()?;
    Ok(WorkbookDraft {
        title: document.title.clone(),
        template_sha256: document.template_sha256.clone(),
        lines,
    })
}

fn comparison_slot(value: &str) -> Result<ComparisonSlot, AppStateError> {
    match value {
        "A" => Ok(ComparisonSlot::A),
        "B" => Ok(ComparisonSlot::B),
        "C" => Ok(ComparisonSlot::C),
        _ => Err(AppStateError::IncompleteComparisons),
    }
}

fn clipboard_rows(document: &EstimateDocument) -> Vec<ClipboardRow> {
    document
        .lines
        .iter()
        .map(|line| {
            let applied = line
                .comparisons
                .iter()
                .find(|comparison| comparison.slot == "A");
            let comparisons = COMPARISON_SLOTS.map(|slot| {
                line.comparisons
                    .iter()
                    .find(|comparison| comparison.slot == slot)
                    .map_or_else(ClipboardComparison::default, |comparison| {
                        ClipboardComparison {
                            company: comparison.company_snapshot.clone(),
                            specification: comparison.spec_snapshot.clone(),
                            product_id: comparison.product_id.clone(),
                            price_won: comparison.price_won_snapshot.to_string(),
                        }
                    })
            });
            ClipboardRow {
                item_name: line.item_name_snapshot.clone(),
                specification: line.spec_snapshot.clone(),
                unit: line.unit_snapshot.clone(),
                applied_price_won: applied
                    .map_or(line.unit_price_won_snapshot, |comparison| {
                        comparison.price_won_snapshot
                    })
                    .to_string(),
                comparisons,
                note: String::new(),
            }
        })
        .collect()
}

fn format_clipboard(rows: &[ClipboardRow]) -> String {
    let mut clipboard = String::from(CLIPBOARD_HEADER);
    for row in rows {
        let fields = [
            row.item_name.as_str(),
            row.specification.as_str(),
            row.unit.as_str(),
            row.applied_price_won.as_str(),
            row.comparisons[0].company.as_str(),
            row.comparisons[0].specification.as_str(),
            row.comparisons[0].product_id.as_str(),
            row.comparisons[0].price_won.as_str(),
            row.comparisons[1].company.as_str(),
            row.comparisons[1].specification.as_str(),
            row.comparisons[1].product_id.as_str(),
            row.comparisons[1].price_won.as_str(),
            row.comparisons[2].company.as_str(),
            row.comparisons[2].specification.as_str(),
            row.comparisons[2].product_id.as_str(),
            row.comparisons[2].price_won.as_str(),
            row.note.as_str(),
        ];
        debug_assert_eq!(fields.len(), CLIPBOARD_COLUMN_COUNT);
        append_clipboard_fields(&mut clipboard, &fields);
        clipboard.push('\n');
    }
    clipboard
}

fn append_clipboard_fields(clipboard: &mut String, fields: &[&str]) {
    for (index, field) in fields.iter().enumerate() {
        if index > 0 {
            clipboard.push('\t');
        }
        append_clipboard_field(clipboard, field);
    }
}

fn append_clipboard_field(clipboard: &mut String, value: &str) {
    let mut normalized = String::with_capacity(value.len());
    let mut replacing_separator = false;
    for character in value.chars() {
        if matches!(character, '\t' | '\r' | '\n') {
            if !replacing_separator {
                normalized.push(' ');
                replacing_separator = true;
            }
        } else {
            normalized.push(character);
            replacing_separator = false;
        }
    }
    if matches!(
        normalized.trim_start().chars().next(),
        Some('=' | '+' | '-' | '@')
    ) {
        clipboard.push('\'');
    }
    clipboard.push_str(&normalized);
}

fn export_base_name(title: &str) -> String {
    let mut sanitized = String::with_capacity(title.len());
    for character in title.chars().take(MAX_EXPORT_TITLE_CHARACTERS) {
        if character.is_control()
            || matches!(
                character,
                '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
            )
        {
            sanitized.push('_');
        } else {
            sanitized.push(character);
        }
    }
    let trimmed = sanitized.trim_matches([' ', '.']);
    if trimmed.is_empty() {
        "관급내역".to_owned()
    } else {
        trimmed.to_owned()
    }
}

fn export_file_name(base_name: &str, attempt: u16) -> String {
    if attempt == 0 {
        format!("{base_name}_관급내역서.xlsx")
    } else {
        format!("{base_name}_관급내역서 ({attempt}).xlsx")
    }
}

const fn route_for_storage(route: DesktopRoute) -> &'static str {
    match route {
        DesktopRoute::Catalog => "catalog",
        DesktopRoute::Estimates => "estimates",
        DesktopRoute::Estimate => "estimate",
        DesktopRoute::Data => "data",
    }
}

fn route_from_storage(value: &str) -> rusqlite::Result<DesktopRoute> {
    match value {
        "catalog" => Ok(DesktopRoute::Catalog),
        "estimates" => Ok(DesktopRoute::Estimates),
        "estimate" => Ok(DesktopRoute::Estimate),
        "data" => Ok(DesktopRoute::Data),
        _ => Err(rusqlite::Error::InvalidColumnType(
            0,
            "route".to_owned(),
            rusqlite::types::Type::Text,
        )),
    }
}

fn validate_view(view: &DesktopViewState) -> Result<(), AppStateError> {
    if view.path.len() > 4_096 || view.path.chars().any(char::is_control) {
        return Err(AppStateError::InvalidView(
            "path contains unsupported characters",
        ));
    }
    let valid = match view.route {
        DesktopRoute::Catalog => view.path == "/",
        DesktopRoute::Estimates => view.path == "/estimates",
        DesktopRoute::Data => view.path == "/data",
        DesktopRoute::Estimate => {
            let Some(id) = view.path.strip_prefix("/estimates/") else {
                return Err(AppStateError::InvalidView(
                    "estimate routes require an estimate ID",
                ));
            };
            !id.is_empty() && !id.contains('/')
        }
    };
    if valid {
        Ok(())
    } else {
        Err(AppStateError::InvalidView("route and path do not match"))
    }
}

fn command_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

fn replay_command_error(error: AppStateError) -> String {
    match error {
        AppStateError::Replay(ReplayError::Transport(_)) => {
            "reconciliation replay failed".to_owned()
        }
        AppStateError::Replay(ReplayError::MalformedPayload { .. }) => {
            "a queued reconciliation change is invalid".to_owned()
        }
        AppStateError::Replay(_) => "reconciliation replay failed".to_owned(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn desktop_view_round_trips_only_valid_route_path_pairs() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let path = temporary.path().join("desktop-view.sqlite3");
        let store = DesktopViewStore::open(path.clone())?;
        let view = DesktopViewState {
            route: DesktopRoute::Estimate,
            path: "/estimates/0123456789abcdef0123456789abcdef".to_owned(),
        };
        assert_eq!(store.load()?, None);
        store.save(&view)?;
        drop(store);

        assert_eq!(DesktopViewStore::open(path)?.load()?, Some(view));
        assert!(
            DesktopViewStore::open(temporary.path().join("invalid.sqlite3"))?
                .save(&DesktopViewState {
                    route: DesktopRoute::Data,
                    path: "/estimates/not-data".to_owned(),
                })
                .is_err()
        );
        Ok(())
    }

    #[test]
    fn clipboard_command_writes_only_the_safe_tsv_projection() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let state = test_state(temporary.path())?;
        state
            .service
            .repository
            .create(document_with_comparisons())?;
        let mut clipboard = RecordingClipboard::default();

        let result =
            copy_estimate_table_inner(&state, "0123456789abcdef0123456789abcdef", &mut clipboard)?;

        assert_eq!(result, ClipboardCopyResult { row_count: 1 });
        let rows = clipboard.value.lines().collect::<Vec<_>>();
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().all(|row| row.split('\t').count() == 17));
        assert_eq!(
            clipboard.value,
            "품명\t규격\t단위\t적용단가\t적용회사\t규격\t물품식별번호\t단가\t회사명\t규격\t물품식별번호\t단가\t회사명\t규격\t물품식별번호\t단가\t비고\n'=품명\t원본 규격\t대\t12500\t'+업체\t'@규격\tC0000001\t12500\tB업체\tB규격\tC0000002\t13000\tC업체\tC규격\tC0000003\t14000\t\n"
        );
        assert!(!clipboard.value.contains("offer-secret"));
        Ok(())
    }

    #[test]
    fn legacy_quantity_values_are_not_exposed_or_exported() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let state = test_state(temporary.path())?;
        state
            .service
            .repository
            .create(document_with_comparisons())?;

        for quantity in ["2", "abc", "1e999"] {
            let connection = rusqlite::Connection::open(temporary.path().join("g2b.sqlite3"))?;
            connection.execute("UPDATE estimate_lines SET quantity = ?1", [quantity])?;
            drop(connection);

            let document = state
                .service
                .repository
                .read("0123456789abcdef0123456789abcdef")?;
            let draft = workbook_draft(&document)?;
            assert_eq!(document.lines[0].quantity, CANONICAL_QUANTITY);
            assert_eq!(draft.lines[0].quantity, CANONICAL_QUANTITY);
        }
        Ok(())
    }

    #[test]
    fn replay_and_resolution_keep_or_discard_exact_durable_mutations() -> Result<(), Box<dyn Error>>
    {
        let temporary = tempdir()?;
        let replay_store = Arc::new(ReplayStore::open(temporary.path().join("replay.sqlite3"))?);
        let state = test_state_with_store(temporary.path(), Arc::clone(&replay_store))?
            .with_replay_target(Box::new(ConflictFirstTarget))?;
        replay_store.enqueue(Mutation::new(
            "estimate-a".to_owned(),
            br#"{"title":"A"}"#.to_vec(),
        ))?;
        replay_store.enqueue(Mutation::new(
            "estimate-b".to_owned(),
            br#"{"title":"B"}"#.to_vec(),
        ))?;

        let conflicted = replay_pending_changes_inner(&state)?;
        assert_eq!(conflicted.state, ReconciliationState::Conflict);
        assert_eq!(conflicted.queued_count, 1);
        assert_eq!(
            conflicted.conflicts,
            vec![ReconciliationConflict {
                sequence: 1,
                entity_id: "estimate-a".to_owned(),
                reason_code: "remote-revision-conflict".to_owned(),
            }]
        );

        let retained_request = ResolveReconciliationConflictRequest {
            sequence: 1,
            resolution: ReconciliationResolution::KeepLocal,
        };
        let retained = resolve_reconciliation_conflict_inner(&state, &retained_request)?;
        assert_eq!(retained.state, ReconciliationState::Queued);
        assert_eq!(retained.queued_count, 1);
        assert!(retained.conflicts.is_empty());

        let state = state.with_replay_target(Box::new(ApplyTarget))?;
        assert_eq!(
            replay_pending_changes_inner(&state)?.state,
            ReconciliationState::Idle
        );
        assert!(replay_store.pending()?.is_empty());

        replay_store.enqueue(Mutation::new(
            "estimate-c".to_owned(),
            br#"{"title":"C"}"#.to_vec(),
        ))?;
        let state = state.with_replay_target(Box::new(ConflictFirstTarget))?;
        let conflict = replay_pending_changes_inner(&state)?;
        assert_eq!(conflict.state, ReconciliationState::Conflict);
        let discarded_request = ResolveReconciliationConflictRequest {
            sequence: 3,
            resolution: ReconciliationResolution::UseRemote,
        };
        let discarded = resolve_reconciliation_conflict_inner(&state, &discarded_request)?;
        assert_eq!(discarded.state, ReconciliationState::Idle);
        assert!(replay_store.pending()?.is_empty());
        Ok(())
    }

    #[test]
    fn default_target_replays_estimate_commands_exactly_once_after_restart()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let replay_path = temporary.path().join("replay.sqlite3");
        let replay_store = Arc::new(ReplayStore::open(&replay_path)?);
        let first_state = test_state_with_store(temporary.path(), Arc::clone(&replay_store))?;
        let create = document_with_comparisons();
        let estimate_id = create.id.clone();
        replay_store.enqueue(create_mutation(&create)?)?;
        drop(first_state);
        drop(replay_store);

        let replay_store = Arc::new(ReplayStore::open(replay_path)?);
        let restored = test_state_with_store(temporary.path(), Arc::clone(&replay_store))?;
        let (status, changes) = replay_pending_changes_with_changes_inner(&restored)?;
        assert_eq!(status.state, ReconciliationState::Idle);
        assert_eq!(
            changes,
            vec![EstimateChangeEvent::saved(estimate_id.clone(), 1)],
            "replay create materialization must notify renderers with its durable revision"
        );
        assert_eq!(
            restored.service.repository.read(&estimate_id)?.revision,
            1,
            "the durable mutation must apply after restart"
        );
        assert!(replay_store.pending()?.is_empty());

        replay_store.enqueue(create_mutation(&create)?)?;
        assert_eq!(
            replay_pending_changes_inner(&restored)?.state,
            ReconciliationState::Idle
        );
        assert_eq!(
            restored.service.repository.read(&estimate_id)?.revision,
            1,
            "replaying an acknowledged create must not create a second document"
        );

        let update = UpdateEstimate {
            expected_revision: 1,
            title: "재생된 수정".to_owned(),
            lines: create.lines.clone(),
            comparisons: create.comparisons.clone(),
        };
        replay_store.enqueue(update_mutation(&estimate_id, &update)?)?;
        let (status, changes) = replay_pending_changes_with_changes_inner(&restored)?;
        assert_eq!(status.state, ReconciliationState::Idle);
        assert_eq!(
            changes,
            vec![EstimateChangeEvent::saved(estimate_id.clone(), 2)]
        );
        let updated = restored.service.repository.read(&estimate_id)?;
        assert_eq!(updated.title, "재생된 수정");
        assert_eq!(updated.revision, 2);

        replay_store.enqueue(update_mutation(&estimate_id, &update)?)?;
        assert_eq!(
            replay_pending_changes_inner(&restored)?.state,
            ReconciliationState::Idle
        );
        assert_eq!(
            restored.service.repository.read(&estimate_id)?.revision,
            2,
            "replaying an acknowledged update must not advance the revision twice"
        );

        let stale = UpdateEstimate {
            expected_revision: 1,
            title: "오래된 수정".to_owned(),
            lines: create.lines,
            comparisons: create.comparisons,
        };
        replay_store.enqueue(update_mutation(&estimate_id, &stale)?)?;
        let conflict = replay_pending_changes_inner(&restored)?;
        assert_eq!(conflict.state, ReconciliationState::Conflict);
        assert_eq!(conflict.conflicts[0].reason_code, REVISION_CONFLICT_REASON);
        let discard = ResolveReconciliationConflictRequest {
            sequence: conflict.conflicts[0].sequence,
            resolution: ReconciliationResolution::UseRemote,
        };
        assert_eq!(
            resolve_reconciliation_conflict_inner(&restored, &discard)?.state,
            ReconciliationState::Idle
        );

        replay_store.enqueue(delete_mutation(&estimate_id)?)?;
        let (status, changes) = replay_pending_changes_with_changes_inner(&restored)?;
        assert_eq!(status.state, ReconciliationState::Idle);
        assert_eq!(
            changes,
            vec![EstimateChangeEvent::deleted(estimate_id.clone())]
        );
        assert!(matches!(
            restored.service.repository.read(&estimate_id),
            Err(EstimateError::NotFound { .. })
        ));

        replay_store.enqueue(delete_mutation(&estimate_id)?)?;
        assert_eq!(
            replay_pending_changes_inner(&restored)?.state,
            ReconciliationState::Idle
        );
        assert!(replay_store.pending()?.is_empty());
        Ok(())
    }

    #[test]
    fn unknown_estimate_replay_operation_fails_closed_and_stays_durable()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let replay_store = Arc::new(ReplayStore::open(temporary.path().join("replay.sqlite3"))?);
        let state = test_state_with_store(temporary.path(), Arc::clone(&replay_store))?;
        replay_store.enqueue(Mutation::new(
            "0123456789abcdef0123456789abcdef".to_owned(),
            br#"{"operation":"shell_execute","id":"0123456789abcdef0123456789abcdef"}"#.to_vec(),
        ))?;

        assert!(matches!(
            replay_pending_changes_inner(&state),
            Err(AppStateError::Replay(ReplayError::MalformedPayload { .. }))
        ));
        assert_eq!(replay_store.pending()?.len(), 1);
        assert!(state.service.repository.list()?.is_empty());
        Ok(())
    }

    #[derive(Default)]
    struct RecordingClipboard {
        value: String,
    }

    impl ClipboardWriter for RecordingClipboard {
        fn write_tsv(&mut self, value: &str) -> Result<(), AppStateError> {
            value.clone_into(&mut self.value);
            Ok(())
        }
    }

    struct ConflictFirstTarget;

    impl ReplayTarget for ConflictFirstTarget {
        fn apply(
            &mut self,
            mutation: &crate::offline_replay::Mutation,
        ) -> Result<ReplayDecision, ReplayError> {
            if mutation.sequence == 1 || mutation.sequence == 3 {
                Ok(ReplayDecision::Conflict {
                    reason: "remote-revision-conflict".to_owned(),
                })
            } else {
                Ok(ReplayDecision::Applied)
            }
        }
    }

    struct ApplyTarget;

    impl ReplayTarget for ApplyTarget {
        fn apply(
            &mut self,
            _mutation: &crate::offline_replay::Mutation,
        ) -> Result<ReplayDecision, ReplayError> {
            Ok(ReplayDecision::Applied)
        }
    }

    fn test_state(directory: &Path) -> Result<DesktopState, Box<dyn Error>> {
        let replay_store = Arc::new(ReplayStore::open(directory.join("replay.sqlite3"))?);
        test_state_with_store(directory, replay_store)
    }

    fn test_state_with_store(
        directory: &Path,
        replay_store: Arc<ReplayStore>,
    ) -> Result<DesktopState, Box<dyn Error>> {
        let database = directory.join("g2b.sqlite3");
        create_estimate_schema(&database)?;
        let workbook = directory.join("template.xlsx");
        let manifest = directory.join("template.json");
        let fallback_image = directory.join("fallback.png");
        fs::write(&workbook, b"workbook template")?;
        fs::write(&manifest, b"template manifest")?;
        fs::write(&fallback_image, b"fallback image")?;
        Ok(DesktopState::new(
            &database,
            directory.join("desktop-view.sqlite3"),
            replay_store,
            TemplateAssets::new(workbook, manifest, fallback_image),
            directory.join("exports"),
        )?)
    }

    fn create_mutation(request: &CreateEstimate) -> Result<Mutation, serde_json::Error> {
        serde_json::to_vec(&serde_json::json!({
            "operation": "create_estimate",
            "request": request,
        }))
        .map(|payload| Mutation::new(request.id.clone(), payload))
    }

    fn update_mutation(id: &str, request: &UpdateEstimate) -> Result<Mutation, serde_json::Error> {
        serde_json::to_vec(&serde_json::json!({
            "operation": "update_estimate",
            "id": id,
            "request": request,
        }))
        .map(|payload| Mutation::new(id.to_owned(), payload))
    }

    fn delete_mutation(id: &str) -> Result<Mutation, serde_json::Error> {
        serde_json::to_vec(&serde_json::json!({
            "operation": "delete_estimate",
            "id": id,
        }))
        .map(|payload| Mutation::new(id.to_owned(), payload))
    }

    fn create_estimate_schema(path: &Path) -> Result<(), rusqlite::Error> {
        let connection = rusqlite::Connection::open(path)?;
        connection.execute_batch(
            "CREATE TABLE IF NOT EXISTS estimate_drafts (
                 id TEXT PRIMARY KEY,
                 title TEXT NOT NULL,
                 template_sha256 TEXT NOT NULL,
                 revision INTEGER NOT NULL DEFAULT 1,
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS estimate_lines (
                 id TEXT PRIMARY KEY,
                 estimate_id TEXT NOT NULL,
                 line_no INTEGER NOT NULL,
                 line_kind TEXT NOT NULL,
                 product_id TEXT NOT NULL,
                 parent_product_id TEXT,
                 relation_id TEXT,
                 offer_operation TEXT,
                 offer_key TEXT,
                 item_name_snapshot TEXT NOT NULL,
                 spec_snapshot TEXT NOT NULL,
                 company_snapshot TEXT NOT NULL,
                 unit_snapshot TEXT NOT NULL,
                 unit_price_won_snapshot INTEGER NOT NULL,
                 quantity NUMERIC NOT NULL
             );
             CREATE TABLE IF NOT EXISTS priority_products (
                 product_id TEXT PRIMARY KEY,
                 detail_url TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS estimate_comparisons (
                 estimate_line_id TEXT NOT NULL,
                 slot TEXT NOT NULL,
                 product_id TEXT NOT NULL,
                 relation_id TEXT,
                 company_snapshot TEXT NOT NULL,
                 spec_snapshot TEXT NOT NULL,
                 price_won_snapshot INTEGER NOT NULL,
                 PRIMARY KEY (estimate_line_id, slot),
                 FOREIGN KEY (estimate_line_id) REFERENCES estimate_lines(id) ON DELETE CASCADE
             );",
        )
    }

    fn document_with_comparisons() -> CreateEstimate {
        let id = "0123456789abcdef0123456789abcdef".to_owned();
        let line_id = "line-1".to_owned();
        CreateEstimate {
            id,
            title: "표 복사".to_owned(),
            template_sha256: "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4"
                .to_owned(),
            lines: vec![EstimateLineInput {
                id: line_id.clone(),
                line_kind: "main".to_owned(),
                product_id: "P0000001".to_owned(),
                parent_product_id: None,
                relation_id: None,
                offer_operation: Some("getThing".to_owned()),
                offer_key: Some("offer-secret".to_owned()),
                item_name_snapshot: "=품명".to_owned(),
                spec_snapshot: "원본 규격".to_owned(),
                company_snapshot: "원본 업체".to_owned(),
                unit_snapshot: "대".to_owned(),
                unit_price_won_snapshot: 10_000,
                quantity: "1".to_owned(),
            }],
            comparisons: vec![
                comparison(&line_id, "A", "C0000001", "+업체", "@규격", 12_500),
                comparison(&line_id, "B", "C0000002", "B업체", "B규격", 13_000),
                comparison(&line_id, "C", "C0000003", "C업체", "C규격", 14_000),
            ],
        }
    }

    fn comparison(
        estimate_line_id: &str,
        slot: &str,
        product_id: &str,
        company_snapshot: &str,
        spec_snapshot: &str,
        price_won_snapshot: i64,
    ) -> EstimateComparisonInput {
        EstimateComparisonInput {
            estimate_line_id: estimate_line_id.to_owned(),
            slot: slot.to_owned(),
            product_id: product_id.to_owned(),
            relation_id: None,
            company_snapshot: company_snapshot.to_owned(),
            spec_snapshot: spec_snapshot.to_owned(),
            price_won_snapshot,
        }
    }
}
