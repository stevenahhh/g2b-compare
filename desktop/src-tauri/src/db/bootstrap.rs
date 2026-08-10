use std::{
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

use fs2::FileExt;
use rusqlite::{Connection, OpenFlags};
use sha2::{Digest, Sha256};
use thiserror::Error;
use zip::ZipArchive;

use super::{CatalogCacheError, CatalogCacheStore};

pub const SUPPORTED_SCHEMA_VERSION: i64 = 1;
pub const MAX_SEED_ARCHIVE_ENTRY_BYTES: u64 = 1024 * 1024 * 1024;

const SEED_ENTRY_NAME: &str = "seed.sqlite3";
const COPY_BUFFER_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BootstrapPaths {
    pub seed_archive: PathBuf,
    pub data: PathBuf,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BootstrapOutcome {
    Installed,
    Existing,
}

#[derive(Debug, Error)]
pub enum BootstrapError {
    #[error("database seed is invalid")]
    InvalidSeed,
    #[error("database schema version {found} is newer than supported version {supported}")]
    SchemaTooNew { found: i64, supported: i64 },
    #[error(transparent)]
    CatalogCache(#[from] CatalogCacheError),
    #[error("database I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("database operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

/// Installs the bundled seed once, then opens the existing user database.
///
/// # Errors
///
/// Returns an error when paths are invalid, the expected seed hash is malformed,
/// the seed archive is corrupt, the existing schema is newer than this release,
/// or SQLite/file operations fail.
pub fn bootstrap_database(
    paths: &BootstrapPaths,
    expected_seed_sha256: &str,
) -> Result<BootstrapOutcome, BootstrapError> {
    let expected_seed_hash = decode_sha256(expected_seed_sha256)?;
    let parent = paths.data.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "database path has no parent directory",
        )
    })?;
    fs::create_dir_all(parent)?;

    let lock_path = paths.data.with_extension("bootstrap.lock");
    let lock = open_lock(&lock_path)?;
    lock.lock_exclusive()?;

    let result = if paths.data.exists() {
        validate_database(&paths.data)?;
        configure_writable_database(&paths.data)?;
        let _ = CatalogCacheStore::initialize(&paths.data)?;
        Ok(BootstrapOutcome::Existing)
    } else {
        install_seed(paths, &expected_seed_hash)
    };

    FileExt::unlock(&lock)?;
    result
}

fn open_lock(path: &Path) -> Result<File, io::Error> {
    OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
}

fn install_seed(
    paths: &BootstrapPaths,
    expected_seed_hash: &[u8; 32],
) -> Result<BootstrapOutcome, BootstrapError> {
    let temporary = paths.data.with_extension("installing");
    remove_if_present(&temporary)?;

    let install_result = (|| {
        extract_seed_archive(&paths.seed_archive, &temporary, expected_seed_hash)?;
        validate_database(&temporary)?;
        fs::rename(&temporary, &paths.data)?;
        configure_writable_database(&paths.data)?;
        let _ = CatalogCacheStore::initialize(&paths.data)?;
        Ok(BootstrapOutcome::Installed)
    })();

    if install_result.is_err() {
        remove_if_present(&temporary)?;
    }
    install_result
}

fn extract_seed_archive(
    archive_path: &Path,
    temporary: &Path,
    expected_seed_hash: &[u8; 32],
) -> Result<(), BootstrapError> {
    let archive_file = File::open(archive_path).map_err(|_| BootstrapError::InvalidSeed)?;
    let mut archive = ZipArchive::new(archive_file).map_err(|_| BootstrapError::InvalidSeed)?;
    if archive.len() != 1 {
        return Err(BootstrapError::InvalidSeed);
    }

    let mut entry = archive
        .by_index(0)
        .map_err(|_| BootstrapError::InvalidSeed)?;
    if entry.name() != SEED_ENTRY_NAME
        || entry.enclosed_name().as_deref() != Some(Path::new(SEED_ENTRY_NAME))
        || entry.is_dir()
        || entry.is_symlink()
        || entry.size() > MAX_SEED_ARCHIVE_ENTRY_BYTES
    {
        return Err(BootstrapError::InvalidSeed);
    }

    let expected_bytes = entry.size();
    let mut destination = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(temporary)?;
    copy_bounded_entry(
        &mut entry,
        &mut destination,
        expected_bytes,
        expected_seed_hash,
    )?;
    destination.sync_all()?;
    Ok(())
}

fn copy_bounded_entry(
    source: &mut impl Read,
    destination: &mut impl Write,
    expected_bytes: u64,
    expected_seed_hash: &[u8; 32],
) -> Result<(), BootstrapError> {
    let mut buffer = vec![0_u8; COPY_BUFFER_BYTES];
    let mut copied = 0_u64;
    let mut hasher = Sha256::new();
    loop {
        let read = source
            .read(&mut buffer)
            .map_err(|_| BootstrapError::InvalidSeed)?;
        if read == 0 {
            break;
        }

        copied = copied
            .checked_add(u64::try_from(read).map_err(|_| BootstrapError::InvalidSeed)?)
            .ok_or(BootstrapError::InvalidSeed)?;
        if copied > MAX_SEED_ARCHIVE_ENTRY_BYTES {
            return Err(BootstrapError::InvalidSeed);
        }
        hasher.update(&buffer[..read]);
        destination.write_all(&buffer[..read])?;
    }

    if copied != expected_bytes {
        return Err(BootstrapError::InvalidSeed);
    }
    let actual_seed_hash: [u8; 32] = hasher.finalize().into();
    if actual_seed_hash != *expected_seed_hash {
        return Err(BootstrapError::InvalidSeed);
    }
    Ok(())
}

fn decode_sha256(value: &str) -> Result<[u8; 32], BootstrapError> {
    let value = value.as_bytes();
    if value.len() != 64 {
        return Err(BootstrapError::InvalidSeed);
    }

    let mut decoded = [0_u8; 32];
    for (index, pair) in value.chunks_exact(2).enumerate() {
        let high = decode_hex_digit(pair[0]).ok_or(BootstrapError::InvalidSeed)?;
        let low = decode_hex_digit(pair[1]).ok_or(BootstrapError::InvalidSeed)?;
        decoded[index] = (high << 4) | low;
    }
    Ok(decoded)
}

const fn decode_hex_digit(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn validate_database(path: &Path) -> Result<(), BootstrapError> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|_| BootstrapError::InvalidSeed)?;
    let check = connection
        .query_row("PRAGMA quick_check", [], |row| row.get::<_, String>(0))
        .map_err(|_| BootstrapError::InvalidSeed)?;
    if check != "ok" {
        return Err(BootstrapError::InvalidSeed);
    }

    let found = connection
        .pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
        .map_err(|_| BootstrapError::InvalidSeed)?;
    if found > SUPPORTED_SCHEMA_VERSION {
        return Err(BootstrapError::SchemaTooNew {
            found,
            supported: SUPPORTED_SCHEMA_VERSION,
        });
    }
    Ok(())
}

fn configure_writable_database(path: &Path) -> Result<(), BootstrapError> {
    let connection = Connection::open(path)?;
    connection.pragma_update(None, "foreign_keys", true)?;
    connection.busy_timeout(Duration::from_secs(5))?;
    let journal_mode = connection.query_row("PRAGMA journal_mode = WAL", [], |row| {
        row.get::<_, String>(0)
    })?;
    if !journal_mode.eq_ignore_ascii_case("wal") {
        return Err(BootstrapError::Sqlite(
            rusqlite::Error::ExecuteReturnedResults,
        ));
    }
    Ok(())
}

fn remove_if_present(path: &Path) -> Result<(), io::Error> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}
