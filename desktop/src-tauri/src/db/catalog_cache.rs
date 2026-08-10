use std::{
    path::{Path, PathBuf},
    time::Duration,
};

use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::Serialize;
use thiserror::Error;

/// The on-disk contract for the desktop's canonical catalog cache.
pub const CATALOG_CACHE_CONTRACT_VERSION: u32 = 1;

const LEGACY_PRIORITY_RELEASE: &str = "priority-catalog";
const CACHE_STATE_TABLE: &str = "desktop_catalog_cache_state";
const CREATE_CACHE_STATE_TABLE: &str = "
CREATE TABLE IF NOT EXISTS desktop_catalog_cache_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    contract_version INTEGER NOT NULL,
    cache_version INTEGER NOT NULL CHECK (cache_version > 0),
    release_identity TEXT NOT NULL
);
";

/// A durable version pin for catalog reads from the canonical `g2b.sqlite3` database.
///
/// `release_identity` is the ready release bundle SHA when the canonical release graph is
/// present. Priority-only seeds deliberately use the stable `priority-catalog` identity; their
/// monotonically increasing `cache_version` is advanced only with a successful local publication.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CatalogCacheVersion {
    pub contract_version: u32,
    pub cache_version: u64,
    pub release_identity: String,
}

impl CatalogCacheVersion {
    /// Returns the stable, versioned namespace for any caller-owned presentation cache.
    #[must_use]
    pub fn cache_key(&self) -> String {
        format!(
            "catalog-cache:v{}:{}:{}",
            self.contract_version, self.release_identity, self.cache_version
        )
    }
}

/// The serializable health state for the persisted catalog version pin.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CatalogCacheState {
    Ready,
}

/// Typed version status exposed to the desktop command boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CatalogCacheStatus {
    pub state: CatalogCacheState,
    #[serde(flatten)]
    pub version: CatalogCacheVersion,
    pub cache_key: String,
}

impl From<CatalogCacheVersion> for CatalogCacheStatus {
    fn from(version: CatalogCacheVersion) -> Self {
        let cache_key = version.cache_key();
        Self {
            state: CatalogCacheState::Ready,
            version,
            cache_key,
        }
    }
}

/// Credential-safe failures from the catalog cache contract.
#[derive(Debug, Error)]
pub enum CatalogCacheError {
    #[error("catalog-cache-unavailable")]
    Unavailable,
    #[error("catalog-cache-corrupt")]
    Corrupt,
    #[error("catalog-cache-contract-version-mismatch")]
    ContractVersionMismatch,
    #[error("catalog-cache-release-mismatch")]
    ReleaseMismatch,
    #[error("catalog-cache-version-mismatch")]
    VersionMismatch,
}

/// Read-only access to the durable catalog version pin stored with `g2b.sqlite3`.
#[derive(Clone, Debug)]
pub struct CatalogCacheStore {
    database: PathBuf,
}

impl CatalogCacheStore {
    /// Creates the one-row contract on the canonical database, or validates the existing row.
    ///
    /// This is intentionally a narrow state record rather than a catalog-data migration: catalog
    /// rows remain solely in the canonical local database and are never copied into a cache.
    ///
    /// # Errors
    ///
    /// Returns an error when the canonical database cannot be opened or its cache/release metadata
    /// is invalid.
    pub fn initialize(
        database: impl AsRef<Path>,
    ) -> Result<CatalogCacheVersion, CatalogCacheError> {
        let database = database.as_ref();
        let connection = open_read_write(database)?;
        ensure_cache_state(&connection)
    }

    /// Opens an already initialized cache contract and validates its persisted version.
    ///
    /// # Errors
    ///
    /// Returns an error when the persisted contract is missing, corrupt, unsupported, or bound to
    /// a different canonical release.
    pub fn open(database: impl Into<PathBuf>) -> Result<Self, CatalogCacheError> {
        let store = Self {
            database: database.into(),
        };
        let _ = store.version()?;
        Ok(store)
    }

    /// Returns the currently validated persisted version for a new catalog operation.
    ///
    /// # Errors
    ///
    /// Returns an error when the canonical database or its persisted version pin is unavailable or
    /// invalid.
    pub fn version(&self) -> Result<CatalogCacheVersion, CatalogCacheError> {
        let connection = Connection::open_with_flags(
            &self.database,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|_| CatalogCacheError::Unavailable)?;
        connection
            .pragma_update(None, "query_only", true)
            .map_err(|_| CatalogCacheError::Unavailable)?;
        read_cache_state(&connection)
    }

    /// Returns the typed valid status used by the command boundary.
    ///
    /// # Errors
    ///
    /// Returns an error when the persisted version pin cannot be validated.
    pub fn status(&self) -> Result<CatalogCacheStatus, CatalogCacheError> {
        self.version().map(CatalogCacheStatus::from)
    }
}
/// Advances the canonical cache version inside the caller's publication transaction.
///
/// Calling this before a transaction commits is deliberate: any later publication failure rolls
/// back the version advance with the catalog rows and checkpoint.
///
/// # Errors
///
/// Returns an error when the caller's transaction cannot validate or update the canonical cache
/// contract.
pub fn advance_catalog_cache_version(
    connection: &Connection,
) -> Result<CatalogCacheVersion, CatalogCacheError> {
    let current = ensure_cache_state(connection)?;
    let next_version = current
        .cache_version
        .checked_add(1)
        .ok_or(CatalogCacheError::Corrupt)?;
    let updated = connection
        .execute(
            "UPDATE desktop_catalog_cache_state
             SET cache_version = ?1
             WHERE singleton = 1 AND cache_version = ?2",
            params![
                i64::try_from(next_version).map_err(|_| CatalogCacheError::Corrupt)?,
                i64::try_from(current.cache_version).map_err(|_| CatalogCacheError::Corrupt)?,
            ],
        )
        .map_err(|_| CatalogCacheError::Unavailable)?;
    if updated != 1 {
        return Err(CatalogCacheError::VersionMismatch);
    }
    Ok(CatalogCacheVersion {
        cache_version: next_version,
        ..current
    })
}

/// Rejects a catalog read when its pin no longer equals the persisted validated version.
///
/// # Errors
///
/// Returns an error when the canonical contract is corrupt, release metadata has changed, or the
/// supplied pin is stale.
pub fn validate_catalog_cache_version(
    connection: &Connection,
    version: &CatalogCacheVersion,
) -> Result<(), CatalogCacheError> {
    if read_cache_state(connection)? == *version {
        Ok(())
    } else {
        Err(CatalogCacheError::VersionMismatch)
    }
}

fn open_read_write(database: &Path) -> Result<Connection, CatalogCacheError> {
    let connection = Connection::open(database).map_err(|_| CatalogCacheError::Unavailable)?;
    connection
        .busy_timeout(Duration::from_secs(5))
        .map_err(|_| CatalogCacheError::Unavailable)?;
    connection
        .pragma_update(None, "foreign_keys", true)
        .map_err(|_| CatalogCacheError::Unavailable)?;
    Ok(connection)
}

fn ensure_cache_state(connection: &Connection) -> Result<CatalogCacheVersion, CatalogCacheError> {
    connection
        .execute_batch(CREATE_CACHE_STATE_TABLE)
        .map_err(|_| CatalogCacheError::Unavailable)?;
    if raw_cache_state(connection)?.is_some() {
        return read_cache_state(connection);
    }
    let release_identity = canonical_release_identity(connection)?;
    connection
        .execute(
            "INSERT INTO desktop_catalog_cache_state
             (singleton, contract_version, cache_version, release_identity)
             VALUES (1, ?1, 1, ?2)",
            params![i64::from(CATALOG_CACHE_CONTRACT_VERSION), release_identity],
        )
        .map_err(|_| CatalogCacheError::Unavailable)?;
    read_cache_state(connection)
}

fn read_cache_state(connection: &Connection) -> Result<CatalogCacheVersion, CatalogCacheError> {
    let Some((contract_version, cache_version, release_identity)) = raw_cache_state(connection)?
    else {
        return Err(CatalogCacheError::Corrupt);
    };
    let contract_version =
        u32::try_from(contract_version).map_err(|_| CatalogCacheError::Corrupt)?;
    let cache_version = u64::try_from(cache_version).map_err(|_| CatalogCacheError::Corrupt)?;
    if contract_version != CATALOG_CACHE_CONTRACT_VERSION {
        return Err(CatalogCacheError::ContractVersionMismatch);
    }
    if cache_version == 0 || release_identity.is_empty() {
        return Err(CatalogCacheError::Corrupt);
    }
    if release_identity != canonical_release_identity(connection)? {
        return Err(CatalogCacheError::ReleaseMismatch);
    }
    Ok(CatalogCacheVersion {
        contract_version,
        cache_version,
        release_identity,
    })
}

fn raw_cache_state(
    connection: &Connection,
) -> Result<Option<(i64, i64, String)>, CatalogCacheError> {
    let exists = table_exists(connection, CACHE_STATE_TABLE)?;
    if !exists {
        return Ok(None);
    }
    connection
        .query_row(
            "SELECT contract_version, cache_version, release_identity
             FROM desktop_catalog_cache_state WHERE singleton = 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(|_| CatalogCacheError::Unavailable)
}
fn canonical_release_identity(connection: &Connection) -> Result<String, CatalogCacheError> {
    let active_release_exists = table_exists(connection, "active_release")?;
    let release_bundles_exists = table_exists(connection, "release_bundles")?;
    if active_release_exists != release_bundles_exists {
        return Err(CatalogCacheError::Corrupt);
    }
    if !active_release_exists {
        return Ok(LEGACY_PRIORITY_RELEASE.to_owned());
    }
    let active_bundle = connection
        .query_row(
            "SELECT bundle_id FROM active_release WHERE singleton = 1",
            [],
            |row| row.get::<_, i64>(0),
        )
        .optional()
        .map_err(|_| CatalogCacheError::Unavailable)?;
    let Some(bundle_id) = active_bundle else {
        return Ok(LEGACY_PRIORITY_RELEASE.to_owned());
    };
    let bundle_sha = connection
        .query_row(
            "SELECT release_bundle_sha
             FROM release_bundles
             WHERE id = ?1
               AND status = 'ready'
               AND ready_attempt_no = attempt_no
               AND release_bundle_sha IS NOT NULL",
            [bundle_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|_| CatalogCacheError::Unavailable)?
        .ok_or(CatalogCacheError::Corrupt)?;
    if bundle_sha.len() != 64 || !bundle_sha.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(CatalogCacheError::Corrupt);
    }
    Ok(format!("release:{}", bundle_sha.to_ascii_lowercase()))
}

fn table_exists(connection: &Connection, table: &str) -> Result<bool, CatalogCacheError> {
    connection
        .query_row(
            "SELECT EXISTS(
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1
            )",
            [table],
            |row| row.get::<_, i64>(0),
        )
        .map(|value| value == 1)
        .map_err(|_| CatalogCacheError::Unavailable)
}
#[cfg(test)]
mod tests {
    use std::{error::Error, fs};

    use rusqlite::Connection;
    use tempfile::tempdir;

    use super::{
        CATALOG_CACHE_CONTRACT_VERSION, CatalogCacheError, CatalogCacheStore,
        advance_catalog_cache_version, validate_catalog_cache_version,
    };

    #[test]
    fn stable_cache_key_survives_restart_without_a_ttl() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let installed = CatalogCacheStore::initialize(&database)?;
        let key = installed.cache_key();
        drop(installed);

        let restored = CatalogCacheStore::open(&database)?;
        let status = restored.status()?;

        assert_eq!(status.version.cache_version, 1);
        assert_eq!(
            status.version.contract_version,
            CATALOG_CACHE_CONTRACT_VERSION
        );
        assert_eq!(status.cache_key, key);
        assert_eq!(status.version.release_identity, "priority-catalog");
        Ok(())
    }

    #[test]
    fn canonical_ready_release_identity_is_persisted_and_revalidated() -> Result<(), Box<dyn Error>>
    {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let connection = Connection::open(&database)?;
        connection.execute_batch(
            "CREATE TABLE active_release (
                singleton INTEGER PRIMARY KEY,
                bundle_id INTEGER NOT NULL
            );
            CREATE TABLE release_bundles (
                id INTEGER PRIMARY KEY,
                release_bundle_sha TEXT,
                status TEXT NOT NULL,
                attempt_no INTEGER NOT NULL,
                ready_attempt_no INTEGER
            );",
        )?;
        connection.execute(
            "INSERT INTO release_bundles VALUES (1, ?1, 'ready', 1, 1)",
            ["a".repeat(64)],
        )?;
        connection.execute("INSERT INTO active_release VALUES (1, 1)", [])?;
        drop(connection);

        let version = CatalogCacheStore::initialize(&database)?;
        assert_eq!(
            version.release_identity,
            format!("release:{}", "a".repeat(64))
        );

        Connection::open(&database)?.execute(
            "UPDATE release_bundles SET release_bundle_sha = ?1 WHERE id = 1",
            ["b".repeat(64)],
        )?;
        assert!(matches!(
            CatalogCacheStore::open(&database),
            Err(CatalogCacheError::ReleaseMismatch)
        ));
        Ok(())
    }

    #[test]
    fn detects_corruption_and_contract_version_mismatch() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        CatalogCacheStore::initialize(&database)?;
        Connection::open(&database)?.execute(
            "UPDATE desktop_catalog_cache_state SET contract_version = 2 WHERE singleton = 1",
            [],
        )?;
        assert!(matches!(
            CatalogCacheStore::open(&database),
            Err(CatalogCacheError::ContractVersionMismatch)
        ));

        fs::write(&database, b"not a sqlite database")?;
        assert!(matches!(
            CatalogCacheStore::open(&database),
            Err(CatalogCacheError::Unavailable)
        ));
        Ok(())
    }

    #[test]
    fn transaction_rollback_retains_last_good_version() -> Result<(), Box<dyn Error>> {
        let temporary = tempdir()?;
        let database = temporary.path().join("g2b.sqlite3");
        let first = CatalogCacheStore::initialize(&database)?;
        let connection = Connection::open(&database)?;
        connection.execute_batch("BEGIN IMMEDIATE")?;
        assert_eq!(advance_catalog_cache_version(&connection)?.cache_version, 2);
        connection.execute_batch("ROLLBACK")?;
        assert_eq!(CatalogCacheStore::open(&database)?.version()?, first);

        let old_pin = first;
        connection.execute_batch("BEGIN IMMEDIATE")?;
        let advanced = advance_catalog_cache_version(&connection)?;
        connection.execute_batch("COMMIT")?;
        assert_eq!(advanced.cache_version, 2);
        assert!(matches!(
            validate_catalog_cache_version(&connection, &old_pin),
            Err(CatalogCacheError::VersionMismatch)
        ));
        assert_eq!(CatalogCacheStore::open(database)?.version()?, advanced);
        Ok(())
    }
}
