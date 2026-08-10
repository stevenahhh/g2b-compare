use std::{
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicU64, Ordering},
    },
    time::{SystemTime, UNIX_EPOCH},
};

use rusqlite::{Connection, OpenFlags, OptionalExtension};
use tauri::{Manager, State, WebviewWindow};
use thiserror::Error;

use crate::catalog::{
    AddCatalogItemRequest, AddCatalogItemResult, CatalogError, CatalogItemAddError,
    CatalogItemAdder, CatalogLineKind, CatalogRepository,
};

use super::{
    CreateEstimate, EstimateDocument, EstimateError, EstimateLineInput, EstimateRepository,
    EstimateSummary, EstimateViewState, RefreshEstimateComparisons, UpdateEstimate,
    events::{EstimateChangeEvent, emit_estimate_change_to_other_windows},
    view_store::{EstimateViewStore, EstimateViewStoreError},
};

const DEFAULT_TEMPLATE_SHA256: &str =
    "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4";

static ID_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Error)]
pub enum EstimateStateError {
    #[error(transparent)]
    Repository(#[from] EstimateError),
    #[error(transparent)]
    ViewStore(#[from] EstimateViewStoreError),
    #[error("estimate application state lock is poisoned")]
    LockPoisoned,
    #[error(transparent)]
    CatalogSelection(#[from] CatalogSelectionError),
}

#[derive(Debug, Error)]
pub enum CatalogSelectionError {
    #[error("selected catalog item was not found or is inactive")]
    NotFound,
    #[error(transparent)]
    Catalog(#[from] CatalogError),
    #[error("catalog selection failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

struct EstimateService {
    repository: EstimateRepository,
    view_store: EstimateViewStore,
    operation_lock: Mutex<()>,
}

#[derive(Clone)]
pub struct EstimateState {
    service: Arc<EstimateService>,
}

impl EstimateState {
    /// Creates the estimate command state and initializes its durable active-document store.
    ///
    /// # Errors
    ///
    /// Returns an error when the estimate schema or view database cannot be initialized.
    pub fn new(
        database: impl AsRef<Path>,
        view_database: impl Into<PathBuf>,
    ) -> Result<Self, EstimateStateError> {
        Ok(Self {
            service: Arc::new(EstimateService {
                repository: EstimateRepository::open(database)?,
                view_store: EstimateViewStore::open(view_database.into())?,
                operation_lock: Mutex::new(()),
            }),
        })
    }

    fn operation_guard(&self) -> Result<MutexGuard<'_, ()>, EstimateStateError> {
        self.service
            .operation_lock
            .lock()
            .map_err(|_error| EstimateStateError::LockPoisoned)
    }

    fn add_catalog_selection(
        &self,
        database: &Path,
        request: &AddCatalogItemRequest,
    ) -> Result<AddCatalogItemResult, EstimateStateError> {
        let mut line = resolve_catalog_line(database, request)?;
        line.id = new_identity();

        let _guard = self.operation_guard()?;
        let active_id = self
            .service
            .view_store
            .load()?
            .and_then(|state| state.active_estimate_id);
        let document = if let Some(active_id) = active_id {
            match self.service.repository.append_line(&active_id, &line) {
                Ok(document) => document,
                Err(EstimateError::NotFound { .. }) => self.create_default_with_line(line)?,
                Err(error) => return Err(error.into()),
            }
        } else {
            self.create_default_with_line(line)?
        };
        Ok(AddCatalogItemResult {
            estimate_id: document.id,
            line_count: u64::try_from(document.lines.len())
                .map_err(|_| EstimateError::NumericRange)?,
            revision: document.revision,
        })
    }

    fn create_default_with_line(
        &self,
        line: EstimateLineInput,
    ) -> Result<EstimateDocument, EstimateStateError> {
        let document = self.service.repository.create(CreateEstimate {
            id: new_identity(),
            title: self.service.repository.next_default_title()?,
            template_sha256: DEFAULT_TEMPLATE_SHA256.to_owned(),
            lines: vec![line],
            comparisons: Vec::new(),
        })?;
        self.service.view_store.save(&EstimateViewState {
            active_estimate_id: Some(document.id.clone()),
        })?;
        Ok(document)
    }
}

impl CatalogItemAdder for EstimateState {
    fn add_catalog_item(
        &self,
        database: &Path,
        request: &AddCatalogItemRequest,
    ) -> Result<AddCatalogItemResult, CatalogItemAddError> {
        self.add_catalog_selection(database, request)
            .map_err(|error| CatalogItemAddError::Rejected(error.to_string()))
    }
}

/// Lists durable estimate summaries.
///
/// # Errors
///
/// Returns a displayable command error when the estimate database cannot be read.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn list_estimates(state: State<'_, EstimateState>) -> Result<Vec<EstimateSummary>, String> {
    list_estimates_inner(&state).map_err(command_error)
}

/// Creates a complete estimate and makes it the durable active document.
///
/// # Errors
///
/// Returns a displayable command error when the document cannot be created.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn create_estimate(
    state: State<'_, EstimateState>,
    request: CreateEstimate,
    source: WebviewWindow,
) -> Result<EstimateDocument, String> {
    let document = create_estimate_inner(&state, request).map_err(command_error)?;
    emit_estimate_change_to_other_windows(
        source.app_handle(),
        &source,
        EstimateChangeEvent::saved(&document.id, document.revision),
    )
    .map_err(command_error)?;
    Ok(document)
}

/// Reads one complete estimate.
///
/// # Errors
///
/// Returns a displayable command error when the estimate does not exist or cannot be read.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn read_estimate(
    state: State<'_, EstimateState>,
    id: String,
) -> Result<EstimateDocument, String> {
    read_estimate_inner(&state, &id).map_err(command_error)
}

/// Replaces one estimate after checking the caller's expected revision.
///
/// # Errors
///
/// Returns a displayable command error for stale revisions, invalid contents, or storage failures.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn update_estimate(
    state: State<'_, EstimateState>,
    id: String,
    request: UpdateEstimate,
    source: WebviewWindow,
) -> Result<EstimateDocument, String> {
    let document = update_estimate_inner(&state, &id, request).map_err(command_error)?;
    emit_estimate_change_to_other_windows(
        source.app_handle(),
        &source,
        EstimateChangeEvent::saved(&document.id, document.revision),
    )
    .map_err(command_error)?;
    Ok(document)
}

/// Rebuilds and persists the current catalog's deterministic A/B/C comparisons.
///
/// # Errors
///
/// Returns a displayable command error when the document has changed or no complete comparison
/// selection can be made from the catalog.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn refresh_estimate_comparisons(
    state: State<'_, EstimateState>,
    id: String,
    request: RefreshEstimateComparisons,
    source: WebviewWindow,
) -> Result<EstimateDocument, String> {
    let document =
        refresh_estimate_comparisons_inner(&state, &id, request).map_err(command_error)?;
    emit_estimate_change_to_other_windows(
        source.app_handle(),
        &source,
        EstimateChangeEvent::saved(&document.id, document.revision),
    )
    .map_err(command_error)?;
    Ok(document)
}

/// Deletes one estimate and clears the durable active ID when it references that document.
///
/// # Errors
///
/// Returns a displayable command error when the estimate does not exist or cannot be deleted.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn delete_estimate(
    state: State<'_, EstimateState>,
    id: String,
    source: WebviewWindow,
) -> Result<(), String> {
    delete_estimate_inner(&state, &id).map_err(command_error)?;
    emit_estimate_change_to_other_windows(
        source.app_handle(),
        &source,
        EstimateChangeEvent::deleted(id),
    )
    .map_err(command_error)
}

/// Loads the durable estimate view, if one has been saved.
///
/// # Errors
///
/// Returns a displayable command error when the view database cannot be read.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn load_estimate_view(
    state: State<'_, EstimateState>,
) -> Result<Option<EstimateViewState>, String> {
    load_estimate_view_inner(&state).map_err(command_error)
}

/// Saves the complete estimate view.
///
/// # Errors
///
/// Returns a displayable command error when the view is invalid or cannot be persisted.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn save_estimate_view(
    estimate_state: State<'_, EstimateState>,
    state: EstimateViewState,
) -> Result<(), String> {
    save_estimate_view_inner(&estimate_state, &state).map_err(command_error)
}

fn list_estimates_inner(state: &EstimateState) -> Result<Vec<EstimateSummary>, EstimateStateError> {
    state.service.repository.list().map_err(Into::into)
}

fn create_estimate_inner(
    state: &EstimateState,
    mut request: CreateEstimate,
) -> Result<EstimateDocument, EstimateStateError> {
    let _guard = state.operation_guard()?;
    if request.template_sha256.trim().is_empty() {
        DEFAULT_TEMPLATE_SHA256.clone_into(&mut request.template_sha256);
    }
    let document = state.service.repository.create(request)?;
    state.service.view_store.save(&EstimateViewState {
        active_estimate_id: Some(document.id.clone()),
    })?;
    Ok(document)
}

fn read_estimate_inner(
    state: &EstimateState,
    id: &str,
) -> Result<EstimateDocument, EstimateStateError> {
    state.service.repository.read(id).map_err(Into::into)
}

fn update_estimate_inner(
    state: &EstimateState,
    id: &str,
    request: UpdateEstimate,
) -> Result<EstimateDocument, EstimateStateError> {
    let _guard = state.operation_guard()?;
    state
        .service
        .repository
        .update(id, request)
        .map_err(Into::into)
}

fn refresh_estimate_comparisons_inner(
    state: &EstimateState,
    id: &str,
    request: RefreshEstimateComparisons,
) -> Result<EstimateDocument, EstimateStateError> {
    let _guard = state.operation_guard()?;
    state
        .service
        .repository
        .refresh_comparisons(id, request.expected_revision)
        .map_err(Into::into)
}

fn delete_estimate_inner(state: &EstimateState, id: &str) -> Result<(), EstimateStateError> {
    let _guard = state.operation_guard()?;
    let active_id = state
        .service
        .view_store
        .load()?
        .and_then(|view| view.active_estimate_id);
    state.service.repository.delete(id)?;
    if active_id.as_deref() == Some(id) {
        state.service.view_store.save(&EstimateViewState {
            active_estimate_id: None,
        })?;
    }
    Ok(())
}

fn load_estimate_view_inner(
    state: &EstimateState,
) -> Result<Option<EstimateViewState>, EstimateStateError> {
    state.service.view_store.load().map_err(Into::into)
}

fn save_estimate_view_inner(
    state: &EstimateState,
    view: &EstimateViewState,
) -> Result<(), EstimateStateError> {
    let _guard = state.operation_guard()?;
    state.service.view_store.save(view).map_err(Into::into)
}

fn resolve_catalog_line(
    database: &Path,
    request: &AddCatalogItemRequest,
) -> Result<EstimateLineInput, CatalogSelectionError> {
    match request.line_kind {
        CatalogLineKind::Main => resolve_main_product(database, &request.product_id),
        CatalogLineKind::Option => resolve_option(database, request),
    }
}

fn resolve_main_product(
    database: &Path,
    product_id: &str,
) -> Result<EstimateLineInput, CatalogSelectionError> {
    let connection = open_catalog(database)?;
    connection
        .query_row(
            "SELECT product.category_name, product.spec, product.company_name,
                    product.unit, product.price_won, offer.operation, offer.offer_key
             FROM priority_products AS product
             JOIN priority_product_offers AS offer
               ON offer.product_id = product.product_id AND offer.active = 1
             WHERE product.product_id = ?1
               AND NOT EXISTS (
                   SELECT 1 FROM verified_product_options AS relation
                   WHERE relation.option_product_id = product.product_id
                     AND relation.active = 1
               )
               AND NOT EXISTS (
                   SELECT 1 FROM priority_contract_options AS relation
                   WHERE relation.option_product_id = product.product_id
                     AND relation.active = 1
               )
             ORDER BY (offer.operation = product.operation) DESC,
                      offer.operation, offer.offer_key
             LIMIT 1",
            [product_id],
            |row| {
                Ok(EstimateLineInput {
                    id: String::new(),
                    line_kind: "main".to_owned(),
                    product_id: product_id.to_owned(),
                    parent_product_id: None,
                    relation_id: None,
                    offer_operation: Some(row.get(5)?),
                    offer_key: Some(row.get(6)?),
                    item_name_snapshot: row.get(0)?,
                    spec_snapshot: row.get(1)?,
                    company_snapshot: row.get(2)?,
                    unit_snapshot: row.get(3)?,
                    unit_price_won_snapshot: row.get(4)?,
                    quantity: "1".to_owned(),
                })
            },
        )
        .optional()?
        .ok_or(CatalogSelectionError::NotFound)
}

fn resolve_option(
    database: &Path,
    request: &AddCatalogItemRequest,
) -> Result<EstimateLineInput, CatalogSelectionError> {
    let parent_product_id = request
        .parent_product_id
        .as_deref()
        .ok_or(CatalogSelectionError::NotFound)?;
    let relation_id = request
        .relation_id
        .as_deref()
        .ok_or(CatalogSelectionError::NotFound)?;
    let option = CatalogRepository::open(database)?
        .options(parent_product_id)?
        .into_iter()
        .find(|option| {
            option.parent_product_id == parent_product_id
                && option.product_id == request.product_id
                && option.relation_id == relation_id
        })
        .ok_or(CatalogSelectionError::NotFound)?;
    Ok(EstimateLineInput {
        id: String::new(),
        line_kind: "option".to_owned(),
        product_id: option.product_id,
        parent_product_id: Some(option.parent_product_id),
        relation_id: Some(option.relation_id),
        offer_operation: None,
        offer_key: None,
        item_name_snapshot: option.name,
        spec_snapshot: option.spec,
        company_snapshot: option.company_name,
        unit_snapshot: option.unit,
        unit_price_won_snapshot: option.price_won,
        quantity: "1".to_owned(),
    })
}

fn open_catalog(path: &Path) -> Result<Connection, rusqlite::Error> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.pragma_update(None, "query_only", true)?;
    Ok(connection)
}

fn new_identity() -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let sequence = u128::from(ID_SEQUENCE.fetch_add(1, Ordering::Relaxed));
    let process = u128::from(std::process::id());
    let value = timestamp.rotate_left(29) ^ (sequence << 64) ^ process;
    format!("{value:032x}")
}

fn command_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use std::{error::Error, fs};

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn command_boundary_cruds_documents_and_persists_active_view() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let view_database = temporary.path().join("estimate-view.sqlite3");
        create_fixture(&database)?;
        let state = EstimateState::new(&database, &view_database)?;

        let created = create_estimate_inner(
            &state,
            CreateEstimate {
                id: "0123456789abcdef0123456789abcdef".to_owned(),
                title: "현장 내역서".to_owned(),
                template_sha256: String::new(),
                lines: Vec::new(),
                comparisons: Vec::new(),
            },
        )?;
        assert_eq!(created.template_sha256, DEFAULT_TEMPLATE_SHA256);
        assert_eq!(created.revision, 1);
        assert_eq!(
            load_estimate_view_inner(&state)?,
            Some(EstimateViewState {
                active_estimate_id: Some(created.id.clone()),
            })
        );

        let updated = update_estimate_inner(
            &state,
            &created.id,
            UpdateEstimate {
                expected_revision: created.revision,
                title: "수정된 내역서".to_owned(),
                lines: vec![line_input(
                    "line-main",
                    "main",
                    "P0000001",
                    None,
                    None,
                    1_250,
                )],
                comparisons: Vec::new(),
            },
        )?;
        assert_eq!(updated.revision, 2);
        assert_eq!(read_estimate_inner(&state, &created.id)?, updated);
        assert_eq!(
            list_estimates_inner(&state)?,
            vec![EstimateSummary {
                id: created.id.clone(),
                title: "수정된 내역서".to_owned(),
                revision: 2,
                line_count: 1,
                total_won: 1_250,
                updated_at: updated.updated_at,
            }]
        );
        drop(state);

        let restored = EstimateState::new(&database, &view_database)?;
        assert_eq!(
            load_estimate_view_inner(&restored)?,
            Some(EstimateViewState {
                active_estimate_id: Some(created.id.clone()),
            })
        );
        delete_estimate_inner(&restored, &created.id)?;
        assert!(list_estimates_inner(&restored)?.is_empty());
        assert_eq!(
            load_estimate_view_inner(&restored)?,
            Some(EstimateViewState {
                active_estimate_id: None,
            })
        );
        Ok(())
    }

    #[test]
    fn catalog_add_creates_and_reuses_active_estimate_with_exact_snapshots()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let view_database = temporary.path().join("estimate-view.sqlite3");
        create_fixture(&database)?;
        let state = EstimateState::new(&database, &view_database)?;

        let main_result = state.add_catalog_item(
            &database,
            &AddCatalogItemRequest {
                product_id: "P0000001".to_owned(),
                line_kind: CatalogLineKind::Main,
                parent_product_id: None,
                relation_id: None,
            },
        )?;
        assert_eq!(main_result.line_count, 1);
        assert_eq!(main_result.estimate_id.len(), 32);
        assert!(
            main_result
                .estimate_id
                .chars()
                .all(|character| character.is_ascii_hexdigit())
        );
        let created = read_estimate_inner(&state, &main_result.estimate_id)?;
        assert_eq!(created.revision, 1);
        assert_eq!(created.template_sha256, DEFAULT_TEMPLATE_SHA256);
        assert_eq!(created.lines[0].item_name_snapshot, "본품 이름");
        assert_eq!(created.lines[0].spec_snapshot, "본품 규격");
        assert_eq!(created.lines[0].company_snapshot, "본품 회사");
        assert_eq!(created.lines[0].unit_snapshot, "대");
        assert_eq!(created.lines[0].unit_price_won_snapshot, 12_500);
        assert_eq!(
            created.lines[0].offer_operation.as_deref(),
            Some("getThing")
        );
        assert_eq!(created.lines[0].offer_key.as_deref(), Some("offer-main"));

        let option_result = state.add_catalog_item(
            &database,
            &AddCatalogItemRequest {
                product_id: "O0000001".to_owned(),
                line_kind: CatalogLineKind::Option,
                parent_product_id: Some("P0000001".to_owned()),
                relation_id: Some("R0000001".to_owned()),
            },
        )?;
        assert_eq!(option_result.estimate_id, main_result.estimate_id);
        assert_eq!(option_result.line_count, 2);
        let updated = read_estimate_inner(&state, &main_result.estimate_id)?;
        assert_eq!(updated.revision, 2);
        assert_eq!(updated.lines[1].line_kind, "option");
        assert_eq!(
            updated.lines[1].parent_product_id.as_deref(),
            Some("P0000001")
        );
        assert_eq!(updated.lines[1].relation_id.as_deref(), Some("R0000001"));
        assert_eq!(updated.lines[1].item_name_snapshot, "옵션 이름");
        assert_eq!(updated.lines[1].spec_snapshot, "옵션 규격");
        assert_eq!(updated.lines[1].company_snapshot, "옵션 회사");
        assert_eq!(updated.lines[1].unit_snapshot, "식");
        assert_eq!(updated.lines[1].unit_price_won_snapshot, 3_500);

        let main_request = AddCatalogItemRequest {
            product_id: "P0000001".to_owned(),
            line_kind: CatalogLineKind::Main,
            parent_product_id: None,
            relation_id: None,
        };
        for expected_count in 3..=9 {
            assert_eq!(
                state.add_catalog_item(&database, &main_request)?.line_count,
                expected_count
            );
        }
        let rejected = state
            .add_catalog_item(&database, &main_request)
            .map_err(|error| error.to_string());
        assert_eq!(
            rejected,
            Err("estimate backend rejected the catalog item: an estimate can contain at most nine lines".to_owned())
        );
        let unchanged = read_estimate_inner(&state, &main_result.estimate_id)?;
        assert_eq!(unchanged.revision, 9);
        assert_eq!(unchanged.lines.len(), 9);
        Ok(())
    }

    #[test]
    fn catalog_add_rejects_a_relation_when_the_requested_parent_is_not_its_catalog_parent()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let view_database = temporary.path().join("estimate-view.sqlite3");
        create_fixture(&database)?;
        let state = EstimateState::new(&database, &view_database)?;

        let accepted = state.add_catalog_item(
            &database,
            &AddCatalogItemRequest {
                product_id: "O0000002".to_owned(),
                line_kind: CatalogLineKind::Option,
                parent_product_id: Some("P0000002".to_owned()),
                relation_id: Some("R0000002".to_owned()),
            },
        )?;
        assert_eq!(accepted.line_count, 1);

        let rejected = state.add_catalog_item(
            &database,
            &AddCatalogItemRequest {
                product_id: "O0000002".to_owned(),
                line_kind: CatalogLineKind::Option,
                parent_product_id: Some("P0000001".to_owned()),
                relation_id: Some("R0000002".to_owned()),
            },
        );
        assert_eq!(
            rejected,
            Err(CatalogItemAddError::Rejected(
                "selected catalog item was not found or is inactive".to_owned()
            ))
        );
        let document = read_estimate_inner(&state, &accepted.estimate_id)?;
        assert_eq!(document.lines.len(), 1);
        assert_eq!(
            document.lines[0].parent_product_id.as_deref(),
            Some("P0000002")
        );
        Ok(())
    }

    #[test]
    fn stale_active_id_is_replaced_by_a_valid_default_estimate() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let view_database = temporary.path().join("estimate-view.sqlite3");
        create_fixture(&database)?;
        let state = EstimateState::new(&database, &view_database)?;
        save_estimate_view_inner(
            &state,
            &EstimateViewState {
                active_estimate_id: Some("missing-estimate".to_owned()),
            },
        )?;

        let result = state.add_catalog_item(
            &database,
            &AddCatalogItemRequest {
                product_id: "P0000001".to_owned(),
                line_kind: CatalogLineKind::Main,
                parent_product_id: None,
                relation_id: None,
            },
        )?;
        assert_ne!(result.estimate_id, "missing-estimate");
        assert_eq!(result.line_count, 1);
        let document = read_estimate_inner(&state, &result.estimate_id)?;
        assert_eq!(document.revision, 1);
        assert_eq!(document.lines.len(), 1);
        assert_eq!(document.template_sha256.len(), 64);
        assert_eq!(
            load_estimate_view_inner(&state)?,
            Some(EstimateViewState {
                active_estimate_id: Some(result.estimate_id),
            })
        );
        Ok(())
    }

    #[test]
    fn refresh_command_persists_deterministic_comparisons_and_rejects_stale_revisions()
    -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let view_database = temporary.path().join("estimate-view.sqlite3");
        create_fixture(&database)?;
        let state = EstimateState::new(&database, &view_database)?;
        let created = create_estimate_inner(
            &state,
            CreateEstimate {
                id: "0123456789abcdef0123456789abcdef".to_owned(),
                title: "비교군 새로고침".to_owned(),
                template_sha256: String::new(),
                lines: vec![
                    line_input("line-main", "main", "P0000001", None, None, 12_500),
                    EstimateLineInput {
                        id: "line-option".to_owned(),
                        line_kind: "option".to_owned(),
                        product_id: "O0000001".to_owned(),
                        parent_product_id: Some("P0000001".to_owned()),
                        relation_id: Some("R0000001".to_owned()),
                        offer_operation: None,
                        offer_key: None,
                        item_name_snapshot: "옵션 이름".to_owned(),
                        spec_snapshot: "옵션 규격".to_owned(),
                        company_snapshot: "옵션 회사".to_owned(),
                        unit_snapshot: "식".to_owned(),
                        unit_price_won_snapshot: 3_500,
                        quantity: "1".to_owned(),
                    },
                ],
                comparisons: Vec::new(),
            },
        )?;

        let refreshed = refresh_estimate_comparisons_inner(
            &state,
            &created.id,
            RefreshEstimateComparisons {
                expected_revision: created.revision,
            },
        )?;

        assert_eq!(refreshed.revision, 2);
        assert_eq!(
            refreshed.lines[0]
                .comparisons
                .iter()
                .map(|comparison| comparison.product_id.as_str())
                .collect::<Vec<_>>(),
            ["P0000001", "P0000002", "P0000003"]
        );
        assert_eq!(
            refreshed.lines[1]
                .comparisons
                .iter()
                .map(|comparison| comparison.product_id.as_str())
                .collect::<Vec<_>>(),
            ["O0000001", "O0000002", "O0000003"]
        );
        Connection::open(&database)?.execute_batch(
            "CREATE TRIGGER fail_comparison_refresh
             BEFORE INSERT ON estimate_comparisons
             BEGIN SELECT RAISE(ABORT, 'forced refresh interruption'); END;",
        )?;
        assert!(matches!(
            refresh_estimate_comparisons_inner(
                &state,
                &created.id,
                RefreshEstimateComparisons {
                    expected_revision: refreshed.revision,
                },
            ),
            Err(EstimateStateError::Repository(
                EstimateError::Constraint { .. }
            ))
        ));
        assert_eq!(read_estimate_inner(&state, &created.id)?, refreshed);
        assert!(matches!(
            refresh_estimate_comparisons_inner(
                &state,
                &created.id,
                RefreshEstimateComparisons {
                    expected_revision: created.revision,
                },
            ),
            Err(EstimateStateError::Repository(
                EstimateError::RevisionConflict {
                    expected: 1,
                    actual: 2,
                }
            ))
        ));
        assert_eq!(read_estimate_inner(&state, &created.id)?, refreshed);
        Ok(())
    }

    fn line_input(
        id: &str,
        line_kind: &str,
        product_id: &str,
        parent_product_id: Option<&str>,
        relation_id: Option<&str>,
        price_won: i64,
    ) -> EstimateLineInput {
        EstimateLineInput {
            id: id.to_owned(),
            line_kind: line_kind.to_owned(),
            product_id: product_id.to_owned(),
            parent_product_id: parent_product_id.map(str::to_owned),
            relation_id: relation_id.map(str::to_owned),
            offer_operation: None,
            offer_key: None,
            item_name_snapshot: "품목".to_owned(),
            spec_snapshot: "규격".to_owned(),
            company_snapshot: "회사".to_owned(),
            unit_snapshot: "개".to_owned(),
            unit_price_won_snapshot: price_won,
            quantity: "1".to_owned(),
        }
    }

    fn create_fixture(path: &Path) -> Result<(), Box<dyn Error>> {
        if path.exists() {
            fs::remove_file(path)?;
        }
        let connection = Connection::open(path)?;
        create_estimate_schema(&connection)?;
        create_catalog_schema(&connection)?;
        insert_catalog_rows(&connection)?;
        Ok(())
    }

    fn create_estimate_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
        connection.execute_batch(
            "PRAGMA foreign_keys = ON;
             CREATE TABLE estimate_drafts (
                 id TEXT PRIMARY KEY,
                 title TEXT NOT NULL,
                 template_sha256 TEXT NOT NULL CHECK (length(template_sha256) = 64),
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL
             );
             CREATE TABLE estimate_lines (
                 id TEXT PRIMARY KEY,
                 estimate_id TEXT NOT NULL REFERENCES estimate_drafts(id) ON DELETE CASCADE,
                 line_no INTEGER NOT NULL CHECK (line_no BETWEEN 1 AND 9),
                 line_kind TEXT NOT NULL CHECK (line_kind IN ('main', 'option')),
                 product_id TEXT NOT NULL CHECK (length(product_id) = 8),
                 parent_product_id TEXT,
                 relation_id TEXT,
                 offer_operation TEXT,
                 offer_key TEXT,
                 item_name_snapshot TEXT NOT NULL,
                 spec_snapshot TEXT NOT NULL,
                 company_snapshot TEXT NOT NULL,
                 unit_snapshot TEXT NOT NULL,
                 unit_price_won_snapshot INTEGER NOT NULL CHECK (unit_price_won_snapshot >= 0),
                 quantity NUMERIC NOT NULL CHECK (quantity > 0),
                 UNIQUE (estimate_id, line_no),
                 CHECK (
                     (line_kind = 'main' AND parent_product_id IS NULL AND relation_id IS NULL)
                     OR (line_kind = 'option' AND parent_product_id IS NOT NULL AND relation_id IS NOT NULL)
                 )
             );
             CREATE UNIQUE INDEX estimate_lines_relation_unique
             ON estimate_lines (estimate_id, relation_id) WHERE relation_id IS NOT NULL;
             CREATE TABLE estimate_comparisons (
                 estimate_line_id TEXT NOT NULL REFERENCES estimate_lines(id) ON DELETE CASCADE,
                 slot TEXT NOT NULL CHECK (slot IN ('A', 'B', 'C')),
                 product_id TEXT NOT NULL CHECK (length(product_id) = 8),
                 relation_id TEXT,
                 company_snapshot TEXT NOT NULL,
                 spec_snapshot TEXT NOT NULL,
                 price_won_snapshot INTEGER NOT NULL CHECK (price_won_snapshot >= 0),
                 PRIMARY KEY (estimate_line_id, slot)
             );",
        )
    }

    fn create_catalog_schema(connection: &Connection) -> Result<(), rusqlite::Error> {
        connection.execute_batch(
            "CREATE TABLE priority_companies (
                 name TEXT PRIMARY KEY,
                 source_row INTEGER NOT NULL,
                 location TEXT NOT NULL,
                 company_type TEXT NOT NULL,
                 declared_product_count INTEGER NOT NULL,
                 contract_end_date TEXT NOT NULL
             );
             CREATE TABLE priority_products (
                 product_id TEXT PRIMARY KEY,
                 operation TEXT NOT NULL,
                 contract_number TEXT NOT NULL,
                 contract_sequence TEXT NOT NULL,
                 category_number TEXT NOT NULL,
                 category_name TEXT NOT NULL,
                 detail_category_number TEXT NOT NULL,
                 spec TEXT NOT NULL,
                 company_name TEXT NOT NULL,
                 unit TEXT NOT NULL,
                 price_won INTEGER NOT NULL,
                 contract_method TEXT NOT NULL,
                 delivery_condition TEXT NOT NULL,
                 delivery_days TEXT NOT NULL,
                 contract_end_date TEXT NOT NULL,
                 image_url TEXT NOT NULL,
                 detail_url TEXT NOT NULL,
                 raw_json TEXT NOT NULL,
                 observed_at TEXT NOT NULL,
                 site_status TEXT NOT NULL DEFAULT '',
                 site_crawled_at TEXT NOT NULL DEFAULT ''
             );
             CREATE TABLE priority_product_offers (
                 operation TEXT NOT NULL,
                 offer_key TEXT NOT NULL,
                 product_id TEXT NOT NULL,
                 company_name TEXT NOT NULL DEFAULT '',
                 price_won INTEGER NOT NULL DEFAULT 0,
                 unit TEXT NOT NULL DEFAULT '',
                 contract_method TEXT NOT NULL DEFAULT '',
                 delivery_condition TEXT NOT NULL DEFAULT '',
                 delivery_days TEXT NOT NULL DEFAULT '',
                 contract_end_date TEXT NOT NULL DEFAULT '',
                 image_url TEXT NOT NULL DEFAULT '',
                 detail_url TEXT NOT NULL DEFAULT '',
                 raw_json TEXT NOT NULL DEFAULT '{}',
                 observed_at TEXT NOT NULL DEFAULT '',
                 active INTEGER NOT NULL DEFAULT 1,
                 PRIMARY KEY (operation, offer_key)
             );
             CREATE TABLE priority_options (
                 source_row INTEGER PRIMARY KEY,
                 company_name TEXT NOT NULL,
                 option_kind TEXT NOT NULL,
                 product_id TEXT NOT NULL,
                 item_name TEXT NOT NULL,
                 spec TEXT NOT NULL,
                 price_won INTEGER NOT NULL,
                 details TEXT NOT NULL
             );
             CREATE TABLE priority_product_contract_groups (
                 product_id TEXT PRIMARY KEY,
                 contract_group TEXT NOT NULL
             );
             CREATE TABLE priority_contract_options (
                 contract_group TEXT NOT NULL,
                 relation_id TEXT PRIMARY KEY,
                 option_product_id TEXT NOT NULL,
                 relation_kind TEXT NOT NULL,
                 position INTEGER NOT NULL,
                 company_name TEXT NOT NULL,
                 raw_label TEXT NOT NULL,
                 relation_price_won INTEGER NOT NULL,
                 observed_at TEXT NOT NULL,
                 active INTEGER NOT NULL DEFAULT 1,
                 UNIQUE (contract_group, relation_kind, position)
             );
             CREATE TABLE verified_product_options (
                 relation_id TEXT PRIMARY KEY,
                 parent_operation TEXT NOT NULL,
                 parent_offer_key TEXT NOT NULL,
                 parent_product_id TEXT NOT NULL,
                 option_product_id TEXT NOT NULL,
                 relation_kind TEXT NOT NULL,
                 position INTEGER NOT NULL,
                 company_name TEXT NOT NULL,
                 raw_label TEXT NOT NULL,
                 relation_price_won INTEGER NOT NULL DEFAULT 0,
                 detail_url TEXT NOT NULL,
                 observed_at TEXT NOT NULL,
                 active INTEGER NOT NULL DEFAULT 1
             );",
        )
    }

    fn insert_catalog_rows(connection: &Connection) -> Result<(), rusqlite::Error> {
        connection.execute_batch(
            "INSERT INTO priority_companies VALUES
                 ('본품 회사', 1, '', '', 1, ''),
                 ('B 비교 회사', 2, '', '', 1, ''),
                 ('C 비교 회사', 3, '', '', 1, '');
             INSERT INTO priority_products VALUES (
                 'P0000001', 'getThing', 'C-1', '1', '1', '본품 이름', '1', '본품 규격',
                 '본품 회사', '대', 12500, 'MAS', '현장도착도', '10', '2027-12-31',
                 '', 'https://example.test/main', '{}', '2026-08-04', '', ''
             );
             INSERT INTO priority_products VALUES (
                 'P0000002', 'getThing', 'C-2', '1', '1', '본품 이름', '1', 'B 비교 규격',
                 'B 비교 회사', '대', 13000, 'MAS', '현장도착도', '10', '2027-12-31',
                 '', 'https://example.test/b', '{}', '2026-08-04', '', ''
             );
             INSERT INTO priority_products VALUES (
                 'P0000003', 'getThing', 'C-3', '1', '1', '본품 이름', '1', 'C 비교 규격',
                 'C 비교 회사', '대', 14000, 'MAS', '현장도착도', '10', '2027-12-31',
                 '', 'https://example.test/c', '{}', '2026-08-04', '', ''
             );
             INSERT INTO priority_products VALUES (
                 'O0000001', 'getThing', 'C-2', '1', '1', '옵션 제품', '1', '옵션 제품 규격',
                 '옵션 회사', '식', 3500, 'MAS', '현장도착도', '10', '2027-12-31',
                 '', 'https://example.test/option', '{}', '2026-08-04', '', ''
             );
             INSERT INTO priority_product_offers (
                 operation, offer_key, product_id, company_name, price_won, active
             ) VALUES ('getThing', 'offer-main', 'P0000001', '본품 회사', 12500, 1);
             INSERT INTO priority_options VALUES
                 (1, '옵션 회사', 'additional', 'O0000001', '옵션 이름', '옵션 규격', 3500, ''),
                 (2, 'B 비교 회사', 'additional', 'O0000002', '옵션 이름', 'B 옵션 규격', 3600, ''),
                 (3, 'C 비교 회사', 'additional', 'O0000003', '옵션 이름', 'C 옵션 규격', 3700, '');
             INSERT INTO priority_product_contract_groups VALUES
                 ('P0000001', 'group-1'),
                 ('P0000002', 'group-b');
             INSERT INTO priority_contract_options VALUES
                 ('group-1', 'R0000001', 'O0000001', 'additional', 1,
                  '옵션 회사', '', 3500, '2026-08-04', 1),
                 ('group-b', 'R0000002', 'O0000002', 'additional', 1,
                  'B 비교 회사', '', 3600, '2026-08-04', 1),
                 ('group-c', 'R0000003', 'O0000003', 'additional', 1,
                  'C 비교 회사', '', 3700, '2026-08-04', 1);",
        )
    }
}
