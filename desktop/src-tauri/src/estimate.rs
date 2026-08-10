#[path = "estimate/commands.rs"]
pub(crate) mod commands;
#[path = "estimate/comparison_refresh.rs"]
mod comparison_refresh;
#[path = "estimate/events.rs"]
pub(crate) mod events;
#[path = "estimate/models.rs"]
mod models;
#[path = "estimate/records.rs"]
mod records;
#[path = "estimate/repository.rs"]
mod repository;
#[path = "estimate/view_store.rs"]
mod view_store;

use rusqlite::ErrorCode;

pub use commands::{CatalogSelectionError, EstimateState, EstimateStateError};
pub use models::{
    CANONICAL_QUANTITY, CreateEstimate, EstimateComparison, EstimateComparisonInput,
    EstimateDocument, EstimateError, EstimateLine, EstimateLineInput, EstimateSummary,
    EstimateViewState, RefreshEstimateComparisons, UpdateEstimate,
};
pub use repository::EstimateRepository;

fn map_sqlite(error: rusqlite::Error) -> EstimateError {
    if matches!(
        &error,
        rusqlite::Error::SqliteFailure(details, _) if details.code == ErrorCode::ConstraintViolation
    ) {
        EstimateError::Constraint { source: error }
    } else {
        EstimateError::Sqlite(error)
    }
}
