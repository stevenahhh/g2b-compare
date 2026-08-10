use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::db::MigrationError;

pub const CANONICAL_QUANTITY: &str = "1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CreateEstimate {
    pub id: String,
    pub title: String,
    pub template_sha256: String,
    pub lines: Vec<EstimateLineInput>,
    pub comparisons: Vec<EstimateComparisonInput>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RefreshEstimateComparisons {
    pub expected_revision: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct UpdateEstimate {
    pub expected_revision: i64,
    pub title: String,
    pub lines: Vec<EstimateLineInput>,
    pub comparisons: Vec<EstimateComparisonInput>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EstimateLineInput {
    pub id: String,
    pub line_kind: String,
    pub product_id: String,
    pub parent_product_id: Option<String>,
    pub relation_id: Option<String>,
    pub offer_operation: Option<String>,
    pub offer_key: Option<String>,
    pub item_name_snapshot: String,
    pub spec_snapshot: String,
    pub company_snapshot: String,
    pub unit_snapshot: String,
    pub unit_price_won_snapshot: i64,
    pub quantity: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EstimateComparisonInput {
    pub estimate_line_id: String,
    pub slot: String,
    pub product_id: String,
    pub relation_id: Option<String>,
    pub company_snapshot: String,
    pub spec_snapshot: String,
    pub price_won_snapshot: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EstimateSummary {
    pub id: String,
    pub title: String,
    pub revision: i64,
    pub line_count: u64,
    pub total_won: i64,
    pub updated_at: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EstimateViewState {
    pub active_estimate_id: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EstimateDocument {
    pub id: String,
    pub title: String,
    pub template_sha256: String,
    pub revision: i64,
    pub created_at: String,
    pub updated_at: String,
    pub lines: Vec<EstimateLine>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EstimateLine {
    pub id: String,
    pub line_no: i64,
    pub line_kind: String,
    pub product_id: String,
    pub parent_product_id: Option<String>,
    pub relation_id: Option<String>,
    pub offer_operation: Option<String>,
    pub offer_key: Option<String>,
    pub item_name_snapshot: String,
    pub spec_snapshot: String,
    pub company_snapshot: String,
    pub unit_snapshot: String,
    pub unit_price_won_snapshot: i64,
    pub quantity: String,
    pub comparisons: Vec<EstimateComparison>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EstimateComparison {
    pub estimate_line_id: String,
    pub slot: String,
    pub product_id: String,
    pub relation_id: Option<String>,
    pub company_snapshot: String,
    pub spec_snapshot: String,
    pub price_won_snapshot: i64,
    pub g2b_url: String,
}

#[derive(Debug, Error)]
pub enum EstimateError {
    #[error(transparent)]
    Migration(#[from] MigrationError),
    #[error("estimate {id} was not found")]
    NotFound { id: String },
    #[error("estimate revision conflict: expected {expected}, actual {actual}")]
    RevisionConflict { expected: i64, actual: i64 },
    #[error("estimate value is outside SQLite's supported integer range")]
    NumericRange,
    #[error("estimate quantity must be exactly 1")]
    InvalidQuantity,
    #[error("comparison refresh could not select A/B/C candidates for line {line_id}: {source}")]
    ComparisonSelection {
        line_id: String,
        #[source]
        source: crate::comparison_selection::ComparisonSelectionError,
    },
    #[error("an estimate can contain at most nine lines")]
    LineLimit,
    #[error("estimate constraint violated: {source}")]
    Constraint {
        #[source]
        source: rusqlite::Error,
    },
    #[error("estimate database operation failed: {0}")]
    Sqlite(#[source] rusqlite::Error),
}
