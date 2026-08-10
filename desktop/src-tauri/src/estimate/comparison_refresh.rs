use rusqlite::{Params, Transaction, params};

use crate::comparison_selection::{
    ComparisonCandidate, ComparisonSelectionError, ComparisonSelectionInput, select_comparisons,
};

use super::{EstimateComparisonInput, EstimateError, EstimateLine, map_sqlite};

const SLOTS: [&str; 3] = ["A", "B", "C"];
const UNKNOWN_SOURCE_ROW: i64 = 2_147_483_647;

#[derive(Clone)]
struct CatalogComparison {
    candidate: ComparisonCandidate,
    relation_id: Option<String>,
    spec_snapshot: String,
}

struct RawCatalogComparison {
    product_id: String,
    company: String,
    spec_snapshot: String,
    price_won: i64,
    source_row: i64,
    relation_id: Option<String>,
}

/// Produces complete A/B/C comparison snapshots for every saved line using the current catalog.
///
/// # Errors
///
/// Returns an error when a line has fewer than two eligible company-distinct alternatives or when
/// the catalog cannot be queried. Callers must persist the returned snapshots in their transaction.
pub(super) fn document_comparisons(
    transaction: &Transaction<'_>,
    lines: &[EstimateLine],
) -> Result<Vec<EstimateComparisonInput>, EstimateError> {
    let mut comparisons = Vec::with_capacity(lines.len() * SLOTS.len());
    for line in lines {
        comparisons.extend(line_comparisons(transaction, line)?);
    }
    Ok(comparisons)
}

fn line_comparisons(
    transaction: &Transaction<'_>,
    line: &EstimateLine,
) -> Result<Vec<EstimateComparisonInput>, EstimateError> {
    let selected = CatalogComparison {
        candidate: ComparisonCandidate {
            product_id: line.product_id.clone(),
            company: line.company_snapshot.clone(),
            price_won: line.unit_price_won_snapshot,
            source_row: 1,
        },
        relation_id: line.relation_id.clone(),
        spec_snapshot: line.spec_snapshot.clone(),
    };
    let candidates = if line.line_kind == "main" {
        main_candidates(transaction, line)?
    } else {
        option_candidates(transaction, line)?
    };
    let selected_candidates = select_comparisons(ComparisonSelectionInput {
        selected: selected.candidate.clone(),
        candidates: candidates
            .iter()
            .map(|candidate| candidate.candidate.clone())
            .collect(),
    })
    .map_err(|source| comparison_error(line, source))?;

    selected_candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| {
            let snapshot = if index == 0 {
                &selected
            } else {
                candidates
                    .iter()
                    .find(|item| item.candidate == *candidate)
                    .ok_or_else(|| {
                        comparison_error(line, ComparisonSelectionError::InsufficientCandidates)
                    })?
            };
            Ok(EstimateComparisonInput {
                estimate_line_id: line.id.clone(),
                slot: SLOTS[index].to_owned(),
                product_id: snapshot.candidate.product_id.clone(),
                relation_id: snapshot.relation_id.clone(),
                company_snapshot: snapshot.candidate.company.clone(),
                spec_snapshot: snapshot.spec_snapshot.clone(),
                price_won_snapshot: snapshot.candidate.price_won,
            })
        })
        .collect()
}

fn main_candidates(
    transaction: &Transaction<'_>,
    line: &EstimateLine,
) -> Result<Vec<CatalogComparison>, EstimateError> {
    load_catalog_candidates(
        transaction,
        "SELECT product.product_id, product.company_name, product.spec, product.price_won,
                COALESCE(company.source_row, ?1), NULL
         FROM priority_products AS product
         LEFT JOIN priority_companies AS company ON company.name = product.company_name
         WHERE product.category_number = (
             SELECT category_number FROM priority_products WHERE product_id = ?2
         )
           AND NOT EXISTS (
               SELECT 1
               FROM verified_product_options AS child_relation
               WHERE child_relation.option_product_id = product.product_id
                 AND child_relation.active = 1
           )
           AND NOT EXISTS (
               SELECT 1
               FROM priority_contract_options AS contract_child
               WHERE contract_child.option_product_id = product.product_id
                 AND contract_child.active = 1
           )",
        params![UNKNOWN_SOURCE_ROW, &line.product_id],
    )
}

fn option_candidates(
    transaction: &Transaction<'_>,
    line: &EstimateLine,
) -> Result<Vec<CatalogComparison>, EstimateError> {
    load_catalog_candidates(
        transaction,
        "SELECT relation.option_product_id, relation.company_name,
                COALESCE(NULLIF(option.spec, ''), relation.raw_label),
                relation.relation_price_won,
                CASE
                    WHEN option.source_row > 0 THEN option.source_row
                    ELSE relation.position + 1
                END,
                relation.relation_id
         FROM priority_contract_options AS relation
         LEFT JOIN priority_options AS option
           ON option.company_name = relation.company_name
          AND option.product_id = relation.option_product_id
          AND option.price_won = relation.relation_price_won
         WHERE relation.active = 1
           AND (option.item_name = ?1 OR relation.option_product_id = ?2)",
        params![&line.item_name_snapshot, &line.product_id],
    )
}

fn load_catalog_candidates<P: Params>(
    transaction: &Transaction<'_>,
    query: &str,
    parameters: P,
) -> Result<Vec<CatalogComparison>, EstimateError> {
    let mut statement = transaction.prepare(query).map_err(map_sqlite)?;
    let rows = statement
        .query_map(parameters, |row| {
            Ok(RawCatalogComparison {
                product_id: row.get(0)?,
                company: row.get(1)?,
                spec_snapshot: row.get(2)?,
                price_won: row.get(3)?,
                source_row: row.get(4)?,
                relation_id: row.get(5)?,
            })
        })
        .map_err(map_sqlite)?;
    rows.map(|row| {
        let row = row.map_err(map_sqlite)?;
        Ok(CatalogComparison {
            candidate: ComparisonCandidate {
                product_id: row.product_id,
                company: row.company,
                price_won: row.price_won,
                source_row: u32::try_from(row.source_row)
                    .map_err(|_| EstimateError::NumericRange)?,
            },
            relation_id: row.relation_id,
            spec_snapshot: row.spec_snapshot,
        })
    })
    .collect()
}

fn comparison_error(line: &EstimateLine, source: ComparisonSelectionError) -> EstimateError {
    EstimateError::ComparisonSelection {
        line_id: line.id.clone(),
        source,
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use rusqlite::Connection;

    use super::*;

    #[test]
    fn main_comparisons_exclude_active_option_children_and_keep_selected_a_identity()
    -> Result<(), Box<dyn Error>> {
        let mut connection = Connection::open_in_memory()?;
        connection.execute_batch(
            "CREATE TABLE priority_companies (
                 name TEXT PRIMARY KEY,
                 source_row INTEGER NOT NULL
             );
             CREATE TABLE priority_products (
                 product_id TEXT PRIMARY KEY,
                 category_number TEXT NOT NULL,
                 company_name TEXT NOT NULL,
                 spec TEXT NOT NULL,
                 price_won INTEGER NOT NULL
             );
             CREATE TABLE verified_product_options (
                 option_product_id TEXT NOT NULL,
                 active INTEGER NOT NULL
             );
             CREATE TABLE priority_contract_options (
                 option_product_id TEXT NOT NULL,
                 active INTEGER NOT NULL
             );
             INSERT INTO priority_companies VALUES
                 ('Selected catalog company', 1),
                 ('Contract child B', 2),
                 ('Contract child C', 3),
                 ('Verified child', 4),
                 ('Main B', 5),
                 ('Main C', 6);
             INSERT INTO priority_products VALUES
                 ('10000000', 'same-category', 'Selected catalog company', 'catalog spec', 100),
                 ('90000001', 'same-category', 'Contract child B', 'option spec B', 101),
                 ('90000002', 'same-category', 'Contract child C', 'option spec C', 102),
                 ('90000003', 'same-category', 'Verified child', 'legacy option spec', 103),
                 ('10000001', 'same-category', 'Main B', 'main spec B', 110),
                 ('10000002', 'same-category', 'Main C', 'main spec C', 120);
             INSERT INTO priority_contract_options VALUES
                 ('90000001', 1),
                 ('90000002', 1);
             INSERT INTO verified_product_options VALUES ('90000003', 1);",
        )?;
        let transaction = connection.transaction()?;
        let comparisons = line_comparisons(
            &transaction,
            &EstimateLine {
                id: "line-main".to_owned(),
                line_no: 1,
                line_kind: "main".to_owned(),
                product_id: "10000000".to_owned(),
                parent_product_id: None,
                relation_id: None,
                offer_operation: None,
                offer_key: None,
                item_name_snapshot: "selected item".to_owned(),
                spec_snapshot: "selected snapshot spec".to_owned(),
                company_snapshot: "selected snapshot company".to_owned(),
                unit_snapshot: "each".to_owned(),
                unit_price_won_snapshot: 100,
                quantity: "1".to_owned(),
                comparisons: Vec::new(),
            },
        )?;

        assert_eq!(
            comparisons
                .iter()
                .map(|comparison| (comparison.slot.as_str(), comparison.product_id.as_str()))
                .collect::<Vec<_>>(),
            [("A", "10000000"), ("B", "10000001"), ("C", "10000002")]
        );
        assert_eq!(comparisons[0].company_snapshot, "selected snapshot company");
        assert_eq!(comparisons[0].spec_snapshot, "selected snapshot spec");
        assert_eq!(comparisons[0].price_won_snapshot, 100);
        Ok(())
    }
}
