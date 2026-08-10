use std::{
    path::{Path, PathBuf},
    time::Duration,
};

use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};

use crate::db::{Migration, MigrationAction, MigrationError, apply_migrations};

use super::{
    CANONICAL_QUANTITY, CreateEstimate, EstimateDocument, EstimateError, EstimateLineInput,
    EstimateSummary, UpdateEstimate,
    comparison_refresh::document_comparisons,
    map_sqlite,
    records::{insert_contents, read_document, validate_line_quantity},
};

const REVISION_MIGRATION_VERSION: &str = "desktop_0001_estimate_draft_revision";
const REVISION_COLUMN_CONTRACT: &str =
    "estimate_drafts.revision must be INTEGER NOT NULL DEFAULT 1 and not a primary key";
const ESTIMATE_DRAFTS_TABLE_MISSING: &str = "estimate_drafts table is missing";
const CANONICAL_ESTIMATE_MIGRATIONS: [Migration; 1] = [Migration::with_precondition(
    REVISION_MIGRATION_VERSION,
    "
ALTER TABLE estimate_drafts
ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
",
    revision_migration_action,
)];

#[derive(Clone, Debug)]
pub struct EstimateRepository {
    database: PathBuf,
}

impl EstimateRepository {
    /// Opens a repository after upgrading and verifying the required estimate tables.
    ///
    /// # Errors
    ///
    /// Returns an error when the database cannot be opened, migrated, or lacks the estimate
    /// schema.
    pub fn open(database: impl AsRef<Path>) -> Result<Self, EstimateError> {
        let repository = Self {
            database: database.as_ref().to_path_buf(),
        };
        apply_migrations(&repository.database, &CANONICAL_ESTIMATE_MIGRATIONS)?;
        let connection = repository.connection()?;
        validate_schema(&connection)?;
        Ok(repository)
    }

    /// Lists estimate headers with their line counts and snapshotted totals.
    ///
    /// # Errors
    ///
    /// Returns an error when the estimate database cannot be queried.
    pub fn list(&self) -> Result<Vec<EstimateSummary>, EstimateError> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT draft.id, draft.title, draft.revision, COUNT(line.id),
                        COALESCE(SUM(COALESCE(
                            applied.price_won_snapshot, line.unit_price_won_snapshot
                        )), 0), draft.updated_at
                 FROM estimate_drafts AS draft
                 LEFT JOIN estimate_lines AS line ON line.estimate_id = draft.id
                 LEFT JOIN estimate_comparisons AS applied
                   ON applied.estimate_line_id = line.id AND applied.slot = 'A'
                 GROUP BY draft.id, draft.title, draft.revision, draft.updated_at
                 ORDER BY draft.updated_at DESC, draft.id ASC",
            )
            .map_err(map_sqlite)?;
        let rows = statement
            .query_map([], |row| {
                let line_count = row.get::<_, i64>(3)?;
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    line_count,
                    row.get::<_, i64>(4)?,
                    row.get::<_, String>(5)?,
                ))
            })
            .map_err(map_sqlite)?;
        rows.map(|row| {
            let (id, title, revision, line_count, total_won, updated_at) =
                row.map_err(map_sqlite)?;
            Ok(EstimateSummary {
                id,
                title,
                revision,
                line_count: u64::try_from(line_count).map_err(|_| EstimateError::NumericRange)?,
                total_won,
                updated_at,
            })
        })
        .collect()
    }

    /// Produces the legacy sequence-and-timestamp title for a new visible estimate.
    ///
    /// # Errors
    ///
    /// Returns an error when the estimate database cannot be queried.
    pub fn next_default_title(&self) -> Result<String, EstimateError> {
        let connection = self.connection()?;
        connection
            .query_row(
                "SELECT printf(
                    '%d-%s',
                    (SELECT COUNT(DISTINCT estimate_id) FROM estimate_lines) + 1,
                    strftime('%Y%m%d-%H%M%S', 'now', 'localtime')
                 )",
                [],
                |row| row.get(0),
            )
            .map_err(map_sqlite)
    }

    /// Creates a complete estimate document and its ordered snapshot rows.
    ///
    /// # Errors
    ///
    /// Returns a constraint or database error without committing any part of the document.
    pub fn create(&self, create: CreateEstimate) -> Result<EstimateDocument, EstimateError> {
        let CreateEstimate {
            id,
            title,
            template_sha256,
            lines,
            comparisons,
        } = create;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(map_sqlite)?;
        transaction
            .execute(
                "INSERT INTO estimate_drafts \
                 (id, title, template_sha256, revision, created_at, updated_at) \
                 VALUES (?1, ?2, ?3, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                params![&id, &title, &template_sha256],
            )
            .map_err(map_sqlite)?;
        insert_contents(&transaction, &id, &lines, &comparisons)?;
        transaction.commit().map_err(map_sqlite)?;
        self.read(&id)
    }

    /// Reads one estimate document with lines and comparisons in display order.
    ///
    /// # Errors
    ///
    /// Returns `EstimateError::NotFound` when the document is absent.
    pub fn read(&self, id: &str) -> Result<EstimateDocument, EstimateError> {
        let connection = self.connection()?;
        read_document(&connection, id)
    }

    /// Replaces one document after atomically checking its revision.
    ///
    /// # Errors
    ///
    /// Returns `NotFound`, `RevisionConflict`, a constraint error, or a database error;
    /// failures leave the saved document unchanged.
    pub fn update(
        &self,
        id: &str,
        update: UpdateEstimate,
    ) -> Result<EstimateDocument, EstimateError> {
        let UpdateEstimate {
            expected_revision,
            title,
            lines,
            comparisons,
        } = update;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(map_sqlite)?;
        let actual = transaction
            .query_row(
                "SELECT revision FROM estimate_drafts WHERE id = ?1",
                [id],
                |row| row.get(0),
            )
            .optional()
            .map_err(map_sqlite)?
            .ok_or_else(|| EstimateError::NotFound { id: id.to_owned() })?;
        if actual != expected_revision {
            return Err(EstimateError::RevisionConflict {
                expected: expected_revision,
                actual,
            });
        }
        transaction
            .execute("DELETE FROM estimate_lines WHERE estimate_id = ?1", [id])
            .map_err(map_sqlite)?;
        insert_contents(&transaction, id, &lines, &comparisons)?;
        let updated = transaction
            .execute(
                "UPDATE estimate_drafts
                 SET title = ?1, revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?2",
                params![&title, id],
            )
            .map_err(map_sqlite)?;
        if updated != 1 {
            return Err(EstimateError::NotFound { id: id.to_owned() });
        }
        transaction.commit().map_err(map_sqlite)?;
        self.read(id)
    }

    /// Rebuilds and persists every line's A/B/C comparisons using the current catalog.
    ///
    /// # Errors
    ///
    /// Returns `NotFound`, `RevisionConflict`, a candidate-selection error, or a database error;
    /// failures leave all persisted comparison snapshots unchanged.
    pub fn refresh_comparisons(
        &self,
        id: &str,
        expected_revision: i64,
    ) -> Result<EstimateDocument, EstimateError> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(map_sqlite)?;
        let document = read_document(&transaction, id)?;
        if document.revision != expected_revision {
            return Err(EstimateError::RevisionConflict {
                expected: expected_revision,
                actual: document.revision,
            });
        }
        let comparisons = document_comparisons(&transaction, &document.lines)?;
        transaction
            .execute(
                "DELETE FROM estimate_comparisons
                 WHERE estimate_line_id IN (
                     SELECT id FROM estimate_lines WHERE estimate_id = ?1
                 )",
                [id],
            )
            .map_err(map_sqlite)?;
        for comparison in &comparisons {
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
        let updated = transaction
            .execute(
                "UPDATE estimate_drafts
                 SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?1 AND revision = ?2",
                params![id, expected_revision],
            )
            .map_err(map_sqlite)?;
        if updated != 1 {
            let actual = transaction
                .query_row(
                    "SELECT revision FROM estimate_drafts WHERE id = ?1",
                    [id],
                    |row| row.get(0),
                )
                .optional()
                .map_err(map_sqlite)?
                .ok_or_else(|| EstimateError::NotFound { id: id.to_owned() })?;
            return Err(EstimateError::RevisionConflict {
                expected: expected_revision,
                actual,
            });
        }
        transaction.commit().map_err(map_sqlite)?;
        self.read(id)
    }

    /// Appends one snapshotted line and advances the document revision atomically.
    ///
    /// # Errors
    ///
    /// Returns `NotFound`, `LineLimit`, a constraint error, or a database error;
    /// failures leave the document and its revision unchanged.
    pub fn append_line(
        &self,
        id: &str,
        line: &EstimateLineInput,
    ) -> Result<EstimateDocument, EstimateError> {
        validate_line_quantity(line)?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(map_sqlite)?;
        let revision = transaction
            .query_row(
                "SELECT revision FROM estimate_drafts WHERE id = ?1",
                [id],
                |row| row.get::<_, i64>(0),
            )
            .optional()
            .map_err(map_sqlite)?
            .ok_or_else(|| EstimateError::NotFound { id: id.to_owned() })?;
        let line_count = transaction
            .query_row(
                "SELECT COUNT(*) FROM estimate_lines WHERE estimate_id = ?1",
                [id],
                |row| row.get::<_, i64>(0),
            )
            .map_err(map_sqlite)?;
        if line_count >= 9 {
            return Err(EstimateError::LineLimit);
        }
        let line_no = line_count
            .checked_add(1)
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
                    id,
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
        let updated = transaction
            .execute(
                "UPDATE estimate_drafts
                 SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?1 AND revision = ?2",
                params![id, revision],
            )
            .map_err(map_sqlite)?;
        if updated != 1 {
            let actual = transaction
                .query_row(
                    "SELECT revision FROM estimate_drafts WHERE id = ?1",
                    [id],
                    |row| row.get(0),
                )
                .map_err(map_sqlite)?;
            return Err(EstimateError::RevisionConflict {
                expected: revision,
                actual,
            });
        }
        transaction.commit().map_err(map_sqlite)?;
        self.read(id)
    }

    /// Deletes one document, relying on the schema's foreign-key cascades for child rows.
    ///
    /// # Errors
    ///
    /// Returns `EstimateError::NotFound` when the document is absent.
    pub fn delete(&self, id: &str) -> Result<(), EstimateError> {
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(map_sqlite)?;
        if transaction
            .execute("DELETE FROM estimate_drafts WHERE id = ?1", [id])
            .map_err(map_sqlite)?
            == 0
        {
            return Err(EstimateError::NotFound { id: id.to_owned() });
        }
        transaction.commit().map_err(map_sqlite)
    }

    fn connection(&self) -> Result<Connection, EstimateError> {
        let connection = Connection::open(&self.database).map_err(map_sqlite)?;
        connection
            .pragma_update(None, "foreign_keys", true)
            .map_err(map_sqlite)?;
        connection
            .busy_timeout(Duration::from_secs(5))
            .map_err(map_sqlite)?;
        Ok(connection)
    }
}

fn revision_migration_action(
    transaction: &Transaction<'_>,
    version: &str,
) -> Result<MigrationAction, MigrationError> {
    let mut statement = transaction.prepare("PRAGMA table_info(estimate_drafts)")?;
    let columns = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, i64>(5)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    drop(statement);

    if columns.is_empty() {
        return Err(MigrationError::IncompatibleSchema {
            version: version.to_owned(),
            reason: ESTIMATE_DRAFTS_TABLE_MISSING,
        });
    }
    let Some((_, declared_type, not_null, default_value, primary_key)) =
        columns.iter().find(|(name, ..)| name == "revision")
    else {
        return Ok(MigrationAction::Apply);
    };
    if declared_type.eq_ignore_ascii_case("INTEGER")
        && *not_null == 1
        && default_value.as_deref() == Some("1")
        && *primary_key == 0
    {
        Ok(MigrationAction::RecordOnly)
    } else {
        Err(MigrationError::IncompatibleSchema {
            version: version.to_owned(),
            reason: REVISION_COLUMN_CONTRACT,
        })
    }
}

fn validate_schema(connection: &Connection) -> Result<(), EstimateError> {
    for query in [
        "SELECT id, title, template_sha256, revision, created_at, updated_at FROM estimate_drafts LIMIT 0",
        "SELECT id, estimate_id, line_no, line_kind, product_id, parent_product_id, relation_id, offer_operation, offer_key, item_name_snapshot, spec_snapshot, company_snapshot, unit_snapshot, unit_price_won_snapshot, quantity FROM estimate_lines LIMIT 0",
        "SELECT estimate_line_id, slot, product_id, relation_id, company_snapshot, spec_snapshot, price_won_snapshot FROM estimate_comparisons LIMIT 0",
    ] {
        let _statement = connection.prepare(query).map_err(map_sqlite)?;
    }
    Ok(())
}
