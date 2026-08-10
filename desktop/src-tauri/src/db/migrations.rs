use std::{path::Path, time::Duration};

use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use sha2::{Digest, Sha256};
use thiserror::Error;

const CREATE_MIGRATION_LEDGER: &str = "
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    source_sha TEXT NOT NULL,
    applied_at TEXT NOT NULL
) STRICT;
";

/// Chooses whether an unrecorded migration runs its SQL or is adopted as already applied.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MigrationAction {
    /// Execute the immutable migration source before recording its checksum.
    Apply,
    /// Record the immutable migration checksum without executing its source.
    RecordOnly,
}

/// Validates an unrecorded migration inside its checksum-locked write transaction.
pub type MigrationPrecondition =
    for<'connection> fn(&Transaction<'connection>, &str) -> Result<MigrationAction, MigrationError>;

/// An immutable, forward-only schema change owned by the desktop application.
#[derive(Clone, Copy, Debug)]
pub struct Migration {
    version: &'static str,
    source: &'static str,
    precondition: Option<MigrationPrecondition>,
}

impl Migration {
    /// Defines one migration. Versions are applied in lexicographic order.
    #[must_use]
    pub const fn new(version: &'static str, source: &'static str) -> Self {
        Self {
            version,
            source,
            precondition: None,
        }
    }

    /// Defines a migration that may atomically adopt a compatible existing schema.
    ///
    /// The precondition runs only when this version is absent from the ledger, after the runner
    /// has acquired `BEGIN IMMEDIATE`. It must return `RecordOnly` only when the schema exactly
    /// matches the immutable migration's intended postcondition.
    #[must_use]
    pub const fn with_precondition(
        version: &'static str,
        source: &'static str,
        precondition: MigrationPrecondition,
    ) -> Self {
        Self {
            version,
            source,
            precondition: Some(precondition),
        }
    }
}

/// Failures while applying application-owned `SQLite` migrations.
#[derive(Debug, Error)]
pub enum MigrationError {
    /// More than one migration was supplied for the same immutable version.
    #[error("migration version {version} was supplied more than once")]
    DuplicateVersion {
        /// The duplicate version identifier.
        version: String,
    },
    /// A migration already recorded in the ledger no longer matches its source.
    #[error("migration {version} checksum changed: expected {expected_sha}, found {actual_sha}")]
    ChecksumDrift {
        /// The immutable migration version that changed.
        version: String,
        /// The checksum recorded when the migration was first applied.
        expected_sha: String,
        /// The checksum for the current migration source.
        actual_sha: String,
    },
    /// An existing schema cannot safely be adopted for an unrecorded migration.
    #[error("migration {version} cannot adopt the current schema: {reason}")]
    IncompatibleSchema {
        /// The immutable migration version that could not be adopted.
        version: String,
        /// The schema contract that was not met.
        reason: &'static str,
    },
    /// `SQLite` could not open, lock, or update the application database.
    #[error("migration database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

/// Applies every migration once, in version order, with an immutable checksum ledger.
///
/// All pending migrations and their ledger entries are committed together. `BEGIN IMMEDIATE`
/// serializes concurrent process startup; an error drops the transaction and rolls back every
/// statement from this invocation.
///
/// # Errors
///
/// Returns an error when migrations share a version, an applied checksum changed, or `SQLite`
/// cannot acquire the write transaction, execute a migration statement, or satisfy a migration
/// precondition.
pub fn apply_migrations(
    path: impl AsRef<Path>,
    migrations: &[Migration],
) -> Result<(), MigrationError> {
    let mut connection = Connection::open(path)?;
    connection.busy_timeout(Duration::from_secs(5))?;
    apply_migrations_to_connection(&mut connection, migrations)
}

fn apply_migrations_to_connection(
    connection: &mut Connection,
    migrations: &[Migration],
) -> Result<(), MigrationError> {
    let mut ordered = migrations.to_vec();
    ordered.sort_unstable_by_key(|migration| migration.version);
    ensure_unique_versions(&ordered)?;

    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    transaction.execute_batch(CREATE_MIGRATION_LEDGER)?;

    for migration in ordered {
        let actual_sha = source_sha(migration.source);
        let applied = transaction
            .query_row(
                "SELECT source_sha FROM schema_migrations WHERE version = ?1",
                [migration.version],
                |row| row.get::<_, String>(0),
            )
            .optional()?;
        if let Some(expected_sha) = applied {
            if expected_sha != actual_sha {
                return Err(MigrationError::ChecksumDrift {
                    version: migration.version.to_owned(),
                    expected_sha,
                    actual_sha,
                });
            }
            continue;
        }

        let action = migration
            .precondition
            .map_or(Ok(MigrationAction::Apply), |precondition| {
                precondition(&transaction, migration.version)
            })?;
        if action == MigrationAction::Apply {
            transaction.execute_batch(migration.source)?;
        }
        transaction.execute(
            "INSERT INTO schema_migrations(version, source_sha, applied_at)
             VALUES (?1, ?2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            params![migration.version, actual_sha],
        )?;
    }

    transaction.commit()?;
    Ok(())
}

fn ensure_unique_versions(migrations: &[Migration]) -> Result<(), MigrationError> {
    for versions in migrations.windows(2) {
        if versions[0].version == versions[1].version {
            return Err(MigrationError::DuplicateVersion {
                version: versions[0].version.to_owned(),
            });
        }
    }
    Ok(())
}

fn source_sha(source: &str) -> String {
    let normalized = source.replace("\r\n", "\n");
    format!("{:x}", Sha256::digest(normalized.as_bytes()))
}
