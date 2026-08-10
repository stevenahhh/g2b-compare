use serde::{Deserialize, Serialize};
use thiserror::Error;

const COMPARISON_COUNT: usize = 3;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ComparisonCandidate {
    pub product_id: String,
    pub company: String,
    pub price_won: i64,
    pub source_row: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ComparisonSelectionInput {
    pub selected: ComparisonCandidate,
    pub candidates: Vec<ComparisonCandidate>,
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ComparisonSelectionError {
    #[error("malformed comparison selection input: {0}")]
    MalformedInput(&'static str),
    #[error("two eligible comparison candidates from distinct companies are required")]
    InsufficientCandidates,
}

/// Selects the requested item as A and the two cheapest eligible alternatives as B and C.
///
/// # Errors
///
/// Returns [`ComparisonSelectionError::MalformedInput`] when any supplied item has an empty
/// identity, a negative price, or a zero source row. Returns
/// [`ComparisonSelectionError::InsufficientCandidates`] when two company-distinct alternatives
/// at or above A's price are unavailable.
pub fn select_comparisons(
    input: ComparisonSelectionInput,
) -> Result<Vec<ComparisonCandidate>, ComparisonSelectionError> {
    validate_candidate(&input.selected)?;
    for candidate in &input.candidates {
        validate_candidate(candidate)?;
    }

    let ComparisonSelectionInput {
        selected,
        mut candidates,
    } = input;
    let selected_price_won = selected.price_won;
    candidates.sort_by(|left, right| {
        left.price_won
            .cmp(&right.price_won)
            .then_with(|| left.source_row.cmp(&right.source_row))
            .then_with(|| left.product_id.cmp(&right.product_id))
            .then_with(|| left.company.cmp(&right.company))
    });

    let mut comparisons = Vec::with_capacity(COMPARISON_COUNT);
    comparisons.push(selected);
    for candidate in candidates {
        let already_represented = comparisons.iter().any(|chosen| {
            chosen.company == candidate.company || chosen.product_id == candidate.product_id
        });
        if candidate.price_won < selected_price_won || already_represented {
            continue;
        }

        comparisons.push(candidate);
        if comparisons.len() == COMPARISON_COUNT {
            return Ok(comparisons);
        }
    }

    Err(ComparisonSelectionError::InsufficientCandidates)
}

fn validate_candidate(candidate: &ComparisonCandidate) -> Result<(), ComparisonSelectionError> {
    if candidate.product_id.trim().is_empty() {
        return Err(ComparisonSelectionError::MalformedInput(
            "product_id must not be empty",
        ));
    }
    if candidate.company.trim().is_empty() {
        return Err(ComparisonSelectionError::MalformedInput(
            "company must not be empty",
        ));
    }
    if candidate.price_won < 0 {
        return Err(ComparisonSelectionError::MalformedInput(
            "price_won must not be negative",
        ));
    }
    if candidate.source_row == 0 {
        return Err(ComparisonSelectionError::MalformedInput(
            "source_row must be at least one",
        ));
    }
    Ok(())
}
