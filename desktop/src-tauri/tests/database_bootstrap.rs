use std::{
    error::Error,
    fs::{self, File},
    io::Write,
    path::Path,
    sync::{Arc, Barrier},
    thread,
};

use g2b_compare_desktop_lib::db::{
    BootstrapError, BootstrapOutcome, BootstrapPaths, CatalogCacheError,
    MAX_SEED_ARCHIVE_ENTRY_BYTES, SUPPORTED_SCHEMA_VERSION, bootstrap_database,
};
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use tempfile::{TempDir, tempdir};
use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

const VALID_TEST_SEED_HASH: &str =
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

#[test]
fn seed_archive_matching_the_expected_hash_is_published_atomically() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;

    assert_eq!(
        bootstrap_database(&paths, &expected_hash)?,
        BootstrapOutcome::Installed
    );
    assert_eq!(read_marker(&paths.data)?, "seed");
    assert!(!paths.data.with_extension("installing").exists());
    Ok(())
}

#[test]
fn existing_user_data_remains_untouched_by_a_tampered_seed_archive() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;
    assert_eq!(
        bootstrap_database(&paths, &expected_hash)?,
        BootstrapOutcome::Installed
    );
    write_marker(&paths.data, "user-edited")?;

    let tampered = create_database_bytes("evil", SUPPORTED_SCHEMA_VERSION)?;
    create_archive(&paths.seed_archive, &[("seed.sqlite3", tampered)])?;

    assert_eq!(
        bootstrap_database(&paths, &expected_hash)?,
        BootstrapOutcome::Existing
    );
    assert_eq!(read_marker(&paths.data)?, "user-edited");
    Ok(())
}

#[test]
fn concurrent_first_start_extracts_one_valid_database() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = Arc::new(bootstrap_paths(&temporary));
    let expected_hash = Arc::new(create_valid_seed_archive(
        &paths.seed_archive,
        "seed",
        SUPPORTED_SCHEMA_VERSION,
    )?);

    let workers = 6;
    let barrier = Arc::new(Barrier::new(workers));
    let handles = (0..workers)
        .map(|_| {
            let paths = Arc::clone(&paths);
            let expected_hash = Arc::clone(&expected_hash);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                bootstrap_database(&paths, &expected_hash)
            })
        })
        .collect::<Vec<_>>();

    let mut outcomes = Vec::with_capacity(workers);
    for handle in handles {
        match handle.join() {
            Ok(result) => outcomes.push(result?),
            Err(_) => return Err("database bootstrap worker panicked".into()),
        }
    }

    assert_eq!(
        outcomes
            .iter()
            .filter(|outcome| **outcome == BootstrapOutcome::Installed)
            .count(),
        1
    );
    assert_eq!(read_marker(&paths.data)?, "seed");
    assert_eq!(
        Connection::open(&paths.data)?
            .query_row("PRAGMA quick_check", [], |row| row.get::<_, String>(0))?,
        "ok"
    );
    Ok(())
}

#[test]
fn corrupt_seed_archive_fails_without_a_partial_database() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    fs::write(&paths.seed_archive, b"not a zip archive")?;

    assert_invalid_seed_without_partial_database(&paths, VALID_TEST_SEED_HASH);
    Ok(())
}

#[test]
fn valid_sqlite_archive_with_the_same_shape_and_size_but_different_hash_is_rejected()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_database = create_database_bytes("seed", SUPPORTED_SCHEMA_VERSION)?;
    let tampered_database = create_database_bytes("evil", SUPPORTED_SCHEMA_VERSION)?;
    assert_eq!(expected_database.len(), tampered_database.len());
    assert_ne!(expected_database, tampered_database);
    create_archive(&paths.seed_archive, &[("seed.sqlite3", tampered_database)])?;

    assert_invalid_seed_without_partial_database(&paths, &sha256_hex(&expected_database));
    Ok(())
}

#[test]
fn seed_archive_with_a_corrupt_sqlite_entry_is_rejected() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    create_archive(
        &paths.seed_archive,
        &[("seed.sqlite3", b"not a sqlite database".to_vec())],
    )?;

    assert_invalid_seed_without_partial_database(&paths, VALID_TEST_SEED_HASH);
    Ok(())
}

#[test]
fn seed_archive_with_extra_entries_is_rejected() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let database = create_database_bytes("seed", SUPPORTED_SCHEMA_VERSION)?;
    create_archive(
        &paths.seed_archive,
        &[
            ("seed.sqlite3", database),
            ("unexpected.txt", b"extra".to_vec()),
        ],
    )?;

    assert_invalid_seed_without_partial_database(&paths, VALID_TEST_SEED_HASH);
    Ok(())
}

#[test]
fn seed_archive_with_a_traversal_entry_is_rejected() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let database = create_database_bytes("seed", SUPPORTED_SCHEMA_VERSION)?;
    create_archive(&paths.seed_archive, &[("../seed.sqlite3", database)])?;

    assert_invalid_seed_without_partial_database(&paths, VALID_TEST_SEED_HASH);
    Ok(())
}

#[test]
fn seed_archive_with_an_oversized_entry_is_rejected_before_extraction() -> Result<(), Box<dyn Error>>
{
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;
    declare_oversized_entry(&paths.seed_archive)?;

    assert_invalid_seed_without_partial_database(&paths, &expected_hash);
    Ok(())
}

#[test]
fn startup_rejects_corrupt_existing_canonical_database() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;
    fs::create_dir_all(paths.data.parent().ok_or("missing application directory")?)?;
    fs::write(&paths.data, b"not a sqlite database")?;

    assert!(matches!(
        bootstrap_database(&paths, &expected_hash),
        Err(BootstrapError::InvalidSeed)
    ));
    Ok(())
}

#[test]
fn startup_rejects_an_unsupported_persisted_catalog_cache_contract() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;
    assert_eq!(
        bootstrap_database(&paths, &expected_hash)?,
        BootstrapOutcome::Installed
    );
    Connection::open(&paths.data)?.execute(
        "UPDATE desktop_catalog_cache_state SET contract_version = 2 WHERE singleton = 1",
        [],
    )?;

    assert!(matches!(
        bootstrap_database(&paths, &expected_hash),
        Err(BootstrapError::CatalogCache(
            CatalogCacheError::ContractVersionMismatch
        ))
    ));
    Ok(())
}

#[test]
fn newer_schema_fails_closed() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let paths = bootstrap_paths(&temporary);
    let expected_hash =
        create_valid_seed_archive(&paths.seed_archive, "seed", SUPPORTED_SCHEMA_VERSION)?;
    create_database(
        &paths.data,
        "future",
        SUPPORTED_SCHEMA_VERSION.saturating_add(1),
    )?;

    assert!(matches!(
        bootstrap_database(&paths, &expected_hash),
        Err(BootstrapError::SchemaTooNew {
            found,
            supported: SUPPORTED_SCHEMA_VERSION
        }) if found == SUPPORTED_SCHEMA_VERSION.saturating_add(1)
    ));
    assert_eq!(read_marker(&paths.data)?, "future");
    Ok(())
}

fn bootstrap_paths(temporary: &TempDir) -> BootstrapPaths {
    BootstrapPaths {
        seed_archive: temporary.path().join("seed.sqlite3.zip"),
        data: temporary.path().join("app").join("g2b.sqlite3"),
    }
}

fn assert_invalid_seed_without_partial_database(
    paths: &BootstrapPaths,
    expected_seed_sha256: &str,
) {
    assert!(matches!(
        bootstrap_database(paths, expected_seed_sha256),
        Err(BootstrapError::InvalidSeed)
    ));
    assert!(!paths.data.exists());
    assert!(!paths.data.with_extension("installing").exists());
}

fn create_valid_seed_archive(
    archive: &Path,
    marker: &str,
    user_version: i64,
) -> Result<String, Box<dyn Error>> {
    let database = create_database_bytes(marker, user_version)?;
    let hash = sha256_hex(&database);
    create_archive(archive, &[("seed.sqlite3", database)])?;
    Ok(hash)
}

fn sha256_hex(contents: &[u8]) -> String {
    format!("{:x}", Sha256::digest(contents))
}

fn create_database_bytes(marker: &str, user_version: i64) -> Result<Vec<u8>, Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("seed.sqlite3");
    create_database(&database, marker, user_version)?;
    Ok(fs::read(database)?)
}

fn create_archive(archive: &Path, entries: &[(&str, Vec<u8>)]) -> Result<(), Box<dyn Error>> {
    let output = File::create(archive)?;
    let mut writer = ZipWriter::new(output);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
    for (name, contents) in entries {
        writer.start_file(*name, options)?;
        writer.write_all(contents)?;
    }
    let _ = writer.finish()?;
    Ok(())
}

fn declare_oversized_entry(archive: &Path) -> Result<(), Box<dyn Error>> {
    let mut bytes = fs::read(archive)?;
    let central_directory = bytes
        .windows(4)
        .rposition(|window| window == b"PK\x01\x02")
        .ok_or("central directory entry is missing")?;
    let size_offset = central_directory
        .checked_add(24)
        .ok_or("central directory size offset overflowed")?;
    let size_end = size_offset
        .checked_add(4)
        .ok_or("central directory size end overflowed")?;
    let oversized = u32::try_from(MAX_SEED_ARCHIVE_ENTRY_BYTES.saturating_add(1))?;
    bytes[size_offset..size_end].copy_from_slice(&oversized.to_le_bytes());
    fs::write(archive, bytes)?;
    Ok(())
}

fn create_database(path: &Path, marker: &str, user_version: i64) -> Result<(), Box<dyn Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let connection = Connection::open(path)?;
    connection.execute_batch(
        "CREATE TABLE bootstrap_probe (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            marker TEXT NOT NULL
        );",
    )?;
    connection.execute(
        "INSERT INTO bootstrap_probe (singleton, marker) VALUES (1, ?1)",
        [marker],
    )?;
    connection.pragma_update(None, "user_version", user_version)?;
    Ok(())
}

fn read_marker(path: &Path) -> Result<String, rusqlite::Error> {
    Connection::open(path)?.query_row(
        "SELECT marker FROM bootstrap_probe WHERE singleton = 1",
        [],
        |row| row.get(0),
    )
}

fn write_marker(path: &Path, marker: &str) -> Result<(), rusqlite::Error> {
    Connection::open(path)?.execute(
        "UPDATE bootstrap_probe SET marker = ?1 WHERE singleton = 1",
        [marker],
    )?;
    Ok(())
}
