use rusqlite::{Connection, OptionalExtension, Transaction, params};

use super::{
    CANONICAL_QUANTITY, EstimateComparison, EstimateComparisonInput, EstimateDocument,
    EstimateError, EstimateLine, EstimateLineInput, map_sqlite,
};

pub(super) fn validate_line_quantity(line: &EstimateLineInput) -> Result<(), EstimateError> {
    if line.quantity == CANONICAL_QUANTITY {
        Ok(())
    } else {
        Err(EstimateError::InvalidQuantity)
    }
}

pub(super) fn insert_contents(
    transaction: &Transaction<'_>,
    estimate_id: &str,
    lines: &[EstimateLineInput],
    comparisons: &[EstimateComparisonInput],
) -> Result<(), EstimateError> {
    for line in lines {
        validate_line_quantity(line)?;
    }
    for (index, line) in lines.iter().enumerate() {
        let line_no = i64::try_from(index)
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(EstimateError::NumericRange)?;
        transaction
            .execute(
                "INSERT INTO estimate_lines (
                    id, estimate_id, line_no, line_kind, product_id, parent_product_id,
                    relation_id, offer_operation, offer_key, item_name_snapshot,
                    spec_snapshot, company_snapshot, unit_snapshot, unit_price_won_snapshot,
                    quantity
                 ) VALUES (
                    ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15
                 )",
                params![
                    &line.id,
                    estimate_id,
                    line_no,
                    &line.line_kind,
                    &line.product_id,
                    &line.parent_product_id,
                    &line.relation_id,
                    &line.offer_operation,
                    &line.offer_key,
                    &line.item_name_snapshot,
                    &line.spec_snapshot,
                    &line.company_snapshot,
                    &line.unit_snapshot,
                    line.unit_price_won_snapshot,
                    CANONICAL_QUANTITY,
                ],
            )
            .map_err(map_sqlite)?;
    }
    for comparison in comparisons {
        transaction
            .execute(
                "INSERT INTO estimate_comparisons (
                    estimate_line_id, slot, product_id, relation_id, company_snapshot,
                    spec_snapshot, price_won_snapshot
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    &comparison.estimate_line_id,
                    &comparison.slot,
                    &comparison.product_id,
                    &comparison.relation_id,
                    &comparison.company_snapshot,
                    &comparison.spec_snapshot,
                    comparison.price_won_snapshot,
                ],
            )
            .map_err(map_sqlite)?;
    }
    Ok(())
}

pub(super) fn read_document(
    connection: &Connection,
    id: &str,
) -> Result<EstimateDocument, EstimateError> {
    let mut document = connection
        .query_row(
            "SELECT id, title, template_sha256, revision, created_at, updated_at
             FROM estimate_drafts WHERE id = ?1",
            [id],
            |row| {
                Ok(EstimateDocument {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    template_sha256: row.get(2)?,
                    revision: row.get(3)?,
                    created_at: row.get(4)?,
                    updated_at: row.get(5)?,
                    lines: Vec::new(),
                })
            },
        )
        .optional()
        .map_err(map_sqlite)?
        .ok_or_else(|| EstimateError::NotFound { id: id.to_owned() })?;
    document.lines = read_lines(connection, id)?;
    Ok(document)
}

fn read_lines(
    connection: &Connection,
    estimate_id: &str,
) -> Result<Vec<EstimateLine>, EstimateError> {
    let mut statement = connection
        .prepare(
            "SELECT id, line_no, line_kind, product_id, parent_product_id, relation_id,
                    offer_operation, offer_key, item_name_snapshot, spec_snapshot,
                    company_snapshot, unit_snapshot, unit_price_won_snapshot
             FROM estimate_lines WHERE estimate_id = ?1 ORDER BY line_no, id",
        )
        .map_err(map_sqlite)?;
    let rows = statement
        .query_map([estimate_id], |row| {
            Ok(EstimateLine {
                id: row.get(0)?,
                line_no: row.get(1)?,
                line_kind: row.get(2)?,
                product_id: row.get(3)?,
                parent_product_id: row.get(4)?,
                relation_id: row.get(5)?,
                offer_operation: row.get(6)?,
                offer_key: row.get(7)?,
                item_name_snapshot: row.get(8)?,
                spec_snapshot: row.get(9)?,
                company_snapshot: row.get(10)?,
                unit_snapshot: row.get(11)?,
                unit_price_won_snapshot: row.get(12)?,
                quantity: CANONICAL_QUANTITY.to_owned(),
                comparisons: Vec::new(),
            })
        })
        .map_err(map_sqlite)?;
    let mut lines = rows
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(map_sqlite)?;
    for line in &mut lines {
        line.comparisons = read_comparisons(connection, &line.id)?;
    }
    Ok(lines)
}

fn read_comparisons(
    connection: &Connection,
    estimate_line_id: &str,
) -> Result<Vec<EstimateComparison>, EstimateError> {
    let mut statement = connection
        .prepare(
            "SELECT comparison.estimate_line_id, comparison.slot, comparison.product_id,
                    comparison.relation_id, comparison.company_snapshot,
                    comparison.spec_snapshot, comparison.price_won_snapshot,
                    COALESCE(NULLIF(product.detail_url, ''), NULLIF(parent.detail_url, ''),
                             'https://shop.g2b.go.kr')
             FROM estimate_comparisons AS comparison
             LEFT JOIN priority_products AS product
               ON product.product_id = comparison.product_id
             LEFT JOIN estimate_lines AS line ON line.id = comparison.estimate_line_id
             LEFT JOIN priority_products AS parent ON parent.product_id = line.parent_product_id
             WHERE comparison.estimate_line_id = ?1 ORDER BY comparison.slot",
        )
        .map_err(map_sqlite)?;
    statement
        .query_map([estimate_line_id], |row| {
            Ok(EstimateComparison {
                estimate_line_id: row.get(0)?,
                slot: row.get(1)?,
                product_id: row.get(2)?,
                relation_id: row.get(3)?,
                company_snapshot: row.get(4)?,
                spec_snapshot: row.get(5)?,
                price_won_snapshot: row.get(6)?,
                g2b_url: row.get(7)?,
            })
        })
        .map_err(map_sqlite)?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(map_sqlite)
}
