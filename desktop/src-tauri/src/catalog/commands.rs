use std::{
    io,
    path::{Path, PathBuf},
    process::Command,
    sync::Arc,
};

use tauri::{Manager, State, Url, WebviewWindow};
use thiserror::Error;

use crate::{
    db::{CatalogCacheError, CatalogCacheStatus, CatalogCacheStore},
    estimate::events::{EstimateChangeEvent, emit_estimate_change_to_other_windows},
};

use super::{
    AddCatalogItemRequest, AddCatalogItemResult, CatalogPage, CatalogProduct, CatalogRepository,
    CatalogViewState, ProductSearchRequest, RelationSearchRequest,
    view_store::{CatalogViewStore, CatalogViewStoreError},
};

pub trait CatalogItemAdder: Send + Sync + 'static {
    /// Adds one validated catalog selection to the active estimate.
    ///
    /// # Errors
    ///
    /// Returns a typed integration error when the estimate backend rejects the
    /// selection. Connected backends may create a default active estimate.
    fn add_catalog_item(
        &self,
        database: &Path,
        request: &AddCatalogItemRequest,
    ) -> Result<AddCatalogItemResult, CatalogItemAddError>;
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum CatalogItemAddError {
    #[error("catalog-to-estimate integration is not connected")]
    Unavailable,
    #[error("there is no active estimate")]
    NoActiveEstimate,
    #[error("estimate backend rejected the catalog item: {0}")]
    Rejected(String),
}

#[derive(Debug, Error)]
pub enum CatalogStateError {
    #[error(transparent)]
    Cache(#[from] CatalogCacheError),
    #[error(transparent)]
    ViewStore(#[from] CatalogViewStoreError),
}

#[derive(Debug, Error)]
enum CatalogRequestError {
    #[error("catalog product ID must not be empty")]
    EmptyProductId,
    #[error("main catalog items cannot include a parent product or relation")]
    InvalidMainRelationship,
    #[error("option catalog items require a parent product and relation")]
    InvalidOptionRelationship,
}

impl AddCatalogItemRequest {
    fn validate(&self) -> Result<(), CatalogRequestError> {
        if self.product_id.trim().is_empty() {
            return Err(CatalogRequestError::EmptyProductId);
        }
        match self.line_kind {
            super::CatalogLineKind::Main
                if self.parent_product_id.is_some() || self.relation_id.is_some() =>
            {
                Err(CatalogRequestError::InvalidMainRelationship)
            }
            super::CatalogLineKind::Option
                if self
                    .parent_product_id
                    .as_deref()
                    .is_none_or(|value| value.trim().is_empty())
                    || self
                        .relation_id
                        .as_deref()
                        .is_none_or(|value| value.trim().is_empty()) =>
            {
                Err(CatalogRequestError::InvalidOptionRelationship)
            }
            _ => Ok(()),
        }
    }
}

pub struct CatalogState {
    database: PathBuf,
    cache_store: CatalogCacheStore,
    view_store: CatalogViewStore,
    item_adder: Arc<dyn CatalogItemAdder>,
    url_opener: Arc<dyn ProductUrlOpener>,
}

impl CatalogState {
    /// Creates command state around the bootstrapped catalog database and a
    /// separate durable view database under the application data directory.
    ///
    /// # Errors
    ///
    /// Returns an error when the bootstrapped catalog cache contract or view database is invalid.
    pub fn new(
        database: impl Into<PathBuf>,
        view_database: impl Into<PathBuf>,
    ) -> Result<Self, CatalogStateError> {
        let database = database.into();
        Ok(Self {
            cache_store: CatalogCacheStore::open(database.clone())?,
            database,
            view_store: CatalogViewStore::open(view_database.into())?,
            item_adder: Arc::new(UnavailableCatalogItemAdder),
            url_opener: Arc::new(SystemProductUrlOpener),
        })
    }

    /// Connects the catalog boundary to an estimate implementation.
    #[must_use]
    pub fn with_item_adder(mut self, item_adder: Arc<dyn CatalogItemAdder>) -> Self {
        self.item_adder = item_adder;
        self
    }

    #[cfg(test)]
    fn with_url_opener(mut self, url_opener: Arc<dyn ProductUrlOpener>) -> Self {
        self.url_opener = url_opener;
        self
    }
}

struct UnavailableCatalogItemAdder;

impl CatalogItemAdder for UnavailableCatalogItemAdder {
    fn add_catalog_item(
        &self,
        _database: &Path,
        _request: &AddCatalogItemRequest,
    ) -> Result<AddCatalogItemResult, CatalogItemAddError> {
        Err(CatalogItemAddError::Unavailable)
    }
}

trait ProductUrlOpener: Send + Sync + 'static {
    fn open(&self, url: &Url) -> Result<(), io::Error>;
}

struct SystemProductUrlOpener;

impl ProductUrlOpener for SystemProductUrlOpener {
    fn open(&self, url: &Url) -> Result<(), io::Error> {
        #[cfg(any(
            target_os = "windows",
            target_os = "macos",
            all(unix, not(target_os = "macos"), not(target_os = "android"))
        ))]
        {
            let mut command = product_open_command(url);
            command.spawn().map(|_child| ())
        }
        #[cfg(not(any(
            target_os = "windows",
            target_os = "macos",
            all(unix, not(target_os = "macos"), not(target_os = "android"))
        )))]
        {
            let _url = url;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "opening product URLs is unsupported on this platform",
            ))
        }
    }
}

#[cfg(target_os = "windows")]
fn product_open_command(url: &Url) -> Command {
    let mut command = Command::new("rundll32.exe");
    command.arg("url.dll,FileProtocolHandler").arg(url.as_str());
    command
}

#[cfg(target_os = "macos")]
fn product_open_command(url: &Url) -> Command {
    let mut command = Command::new("open");
    command.arg(url.as_str());
    command
}

#[cfg(all(unix, not(target_os = "macos"), not(target_os = "android")))]
fn product_open_command(url: &Url) -> Command {
    let mut command = Command::new("xdg-open");
    command.arg(url.as_str());
    command
}

/// Searches the bootstrapped product catalog.
///
/// # Errors
///
/// Returns a displayable command error when the request or catalog database is invalid.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn search_products(
    state: State<'_, CatalogState>,
    request: ProductSearchRequest,
) -> Result<CatalogPage<CatalogProduct>, String> {
    search_products_inner(&state, &request)
}

/// Searches catalog relations for one company and category.
///
/// # Errors
///
/// Returns a displayable command error when the request or catalog database is invalid.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn search_relations(
    state: State<'_, CatalogState>,
    request: RelationSearchRequest,
) -> Result<CatalogPage<super::CatalogOption>, String> {
    search_relations_inner(&state, &request)
}

/// Adds a validated catalog item through the configured estimate seam.
///
/// # Errors
///
/// Returns a displayable command error when the request is invalid or no estimate backend is connected.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn add_catalog_item(
    state: State<'_, CatalogState>,
    request: AddCatalogItemRequest,
    source: WebviewWindow,
) -> Result<AddCatalogItemResult, String> {
    let result = add_catalog_item_inner(&state, &request)?;
    emit_estimate_change_to_other_windows(
        source.app_handle(),
        &source,
        EstimateChangeEvent::saved(&result.estimate_id, result.revision),
    )
    .map_err(command_error)?;
    Ok(result)
}

/// Opens a validated HTTP or HTTPS product URL through the platform boundary.
///
/// # Errors
///
/// Returns a displayable command error for an invalid URL or platform launch failure.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn open_product(state: State<'_, CatalogState>, detail_url: String) -> Result<(), String> {
    open_product_inner(&state, &detail_url)
}

/// Loads the durable catalog view, if one has been saved.
///
/// # Errors
///
/// Returns a displayable command error when the view database cannot be read.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn load_catalog_view(
    state: State<'_, CatalogState>,
) -> Result<Option<CatalogViewState>, String> {
    load_catalog_view_inner(&state)
}

/// Saves the complete catalog view to application data.
///
/// # Errors
///
/// Returns a displayable command error when the state is invalid or cannot be persisted.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn save_catalog_view(
    catalog_state: State<'_, CatalogState>,
    state: CatalogViewState,
) -> Result<(), String> {
    save_catalog_view_inner(&catalog_state, &state)
}

/// Returns the validated version pin currently backing every offline catalog search.
///
/// # Errors
///
/// Returns a displayable error when the canonical catalog cache contract is unavailable or invalid.
#[allow(clippy::needless_pass_by_value)]
#[tauri::command]
pub fn get_catalog_cache_status(
    state: State<'_, CatalogState>,
) -> Result<CatalogCacheStatus, String> {
    catalog_cache_status_inner(&state)
}

fn search_products_inner(
    state: &CatalogState,
    request: &ProductSearchRequest,
) -> Result<CatalogPage<CatalogProduct>, String> {
    let version = state.cache_store.version().map_err(command_error)?;
    let repository =
        CatalogRepository::open_with_cache(&state.database, version).map_err(command_error)?;
    repository
        .products(
            &request.company_name,
            &request.query,
            request.sort,
            request.page,
        )
        .map_err(command_error)
}

fn search_relations_inner(
    state: &CatalogState,
    request: &RelationSearchRequest,
) -> Result<CatalogPage<super::CatalogOption>, String> {
    let version = state.cache_store.version().map_err(command_error)?;
    let repository =
        CatalogRepository::open_with_cache(&state.database, version).map_err(command_error)?;
    repository
        .relations(
            &request.parent_product_id,
            &request.company_name,
            request.category,
            &request.query,
            request.sort,
            request.page,
        )
        .map_err(command_error)
}

fn add_catalog_item_inner(
    state: &CatalogState,
    request: &AddCatalogItemRequest,
) -> Result<AddCatalogItemResult, String> {
    request.validate().map_err(command_error)?;
    let _ = state.cache_store.version().map_err(command_error)?;
    state
        .item_adder
        .add_catalog_item(&state.database, request)
        .map_err(command_error)
}

fn open_product_inner(state: &CatalogState, detail_url: &str) -> Result<(), String> {
    let url = Url::parse(detail_url).map_err(|error| format!("invalid product URL: {error}"))?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() {
        return Err("product URL must use http or https and include a host".to_owned());
    }
    state.url_opener.open(&url).map_err(command_error)
}

fn catalog_cache_status_inner(state: &CatalogState) -> Result<CatalogCacheStatus, String> {
    state.cache_store.status().map_err(command_error)
}

fn load_catalog_view_inner(state: &CatalogState) -> Result<Option<CatalogViewState>, String> {
    state.view_store.load().map_err(command_error)
}

fn save_catalog_view_inner(state: &CatalogState, view: &CatalogViewState) -> Result<(), String> {
    state.view_store.save(view).map_err(command_error)
}

fn command_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use tempfile::tempdir;

    use super::*;
    use crate::{
        catalog::{CatalogLineKind, CatalogSort, RelationCategory, RelationValues},
        db::CatalogCacheStore,
    };

    #[derive(Default)]
    struct RecordingAdder {
        calls: Mutex<Vec<(PathBuf, AddCatalogItemRequest)>>,
    }

    impl CatalogItemAdder for RecordingAdder {
        fn add_catalog_item(
            &self,
            database: &Path,
            request: &AddCatalogItemRequest,
        ) -> Result<AddCatalogItemResult, CatalogItemAddError> {
            self.calls
                .lock()
                .map_err(|error| CatalogItemAddError::Rejected(error.to_string()))?
                .push((database.to_path_buf(), request.clone()));
            Ok(AddCatalogItemResult {
                estimate_id: "estimate-1".to_owned(),
                line_count: 4,
                revision: 7,
            })
        }
    }

    #[derive(Default)]
    struct RecordingOpener {
        urls: Mutex<Vec<String>>,
    }

    impl ProductUrlOpener for RecordingOpener {
        fn open(&self, url: &Url) -> Result<(), io::Error> {
            self.urls
                .lock()
                .map_err(|error| io::Error::other(error.to_string()))?
                .push(url.as_str().to_owned());
            Ok(())
        }
    }

    #[test]
    fn add_command_has_an_explicit_unavailable_default_and_a_typed_seam()
    -> Result<(), Box<dyn std::error::Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        CatalogCacheStore::initialize(&database)?;
        let view_database = temporary.path().join("catalog-view.sqlite3");
        let request = AddCatalogItemRequest {
            product_id: "P1".to_owned(),
            line_kind: CatalogLineKind::Option,
            parent_product_id: Some("P0".to_owned()),
            relation_id: Some("R1".to_owned()),
        };
        let disconnected = CatalogState::new(&database, &view_database)?;
        assert_eq!(
            add_catalog_item_inner(&disconnected, &request),
            Err("catalog-to-estimate integration is not connected".to_owned())
        );

        let adder = Arc::new(RecordingAdder::default());
        let connected =
            CatalogState::new(&database, &view_database)?.with_item_adder(adder.clone());
        assert_eq!(
            add_catalog_item_inner(&connected, &request)?,
            AddCatalogItemResult {
                estimate_id: "estimate-1".to_owned(),
                line_count: 4,
                revision: 7,
            }
        );
        assert_eq!(
            *adder
                .calls
                .lock()
                .map_err(|error| io::Error::other(error.to_string()))?,
            vec![(database, request)]
        );
        Ok(())
    }

    #[test]
    fn open_command_accepts_only_hosted_http_urls_before_crossing_platform_boundary()
    -> Result<(), Box<dyn std::error::Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        CatalogCacheStore::initialize(&database)?;
        let opener = Arc::new(RecordingOpener::default());
        let state = CatalogState::new(database, temporary.path().join("catalog-view.sqlite3"))?
            .with_url_opener(opener.clone());

        open_product_inner(&state, "https://example.test/products/P1?tab=detail")?;
        assert!(open_product_inner(&state, "file:///C:/Windows/win.ini").is_err());
        assert!(open_product_inner(&state, "https://").is_err());
        assert_eq!(
            *opener
                .urls
                .lock()
                .map_err(|error| io::Error::other(error.to_string()))?,
            ["https://example.test/products/P1?tab=detail"]
        );
        Ok(())
    }

    #[test]
    fn catalog_view_round_trips_durably_with_frontend_field_shapes()
    -> Result<(), Box<dyn std::error::Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        CatalogCacheStore::initialize(&database)?;
        let view_database = temporary.path().join("catalog-view.sqlite3");
        let state = CatalogState::new(&database, &view_database)?;
        assert_eq!(load_catalog_view_inner(&state)?, None);

        let view = CatalogViewState {
            query: "카메라".to_owned(),
            sort: CatalogSort::NameAsc,
            page: 3,
            selected_product_id: Some("P1".to_owned()),
            active_category: RelationCategory::Additional,
            product_scroll_top: 411.5,
            relation_scroll_top: RelationValues {
                selection: 10.0,
                additional: 20.5,
                construction: 30.0,
            },
            relation_query: RelationValues {
                selection: "브래킷".to_owned(),
                additional: "전원".to_owned(),
                construction: "배선".to_owned(),
            },
            relation_page: RelationValues {
                selection: 1,
                additional: 2,
                construction: 4,
            },
        };
        save_catalog_view_inner(&state, &view)?;
        drop(state);

        let restored = CatalogState::new(database, view_database)?;
        assert_eq!(load_catalog_view_inner(&restored)?, Some(view));
        Ok(())
    }

    #[test]
    fn add_request_enforces_main_and_option_relationship_contracts() {
        let invalid_main = AddCatalogItemRequest {
            product_id: "P1".to_owned(),
            line_kind: CatalogLineKind::Main,
            parent_product_id: Some("P0".to_owned()),
            relation_id: None,
        };
        let invalid_option = AddCatalogItemRequest {
            product_id: "P1".to_owned(),
            line_kind: CatalogLineKind::Option,
            parent_product_id: None,
            relation_id: Some("R1".to_owned()),
        };
        assert!(invalid_main.validate().is_err());
        assert!(invalid_option.validate().is_err());
    }
}
