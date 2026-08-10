use std::{
    error::Error,
    sync::{Arc, Barrier},
    thread,
};

use g2b_compare_desktop_lib::db::{Migration, MigrationError, apply_migrations};
use rusqlite::Connection;

use g2b_compare_desktop_lib::offline_replay::{Mutation, ReplayStore};
use tempfile::tempdir;

#[test]
fn applies_migrations_in_version_order() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("desktop.sqlite3");
    let migrations = [
        Migration::new(
            "0002_insert_second",
            "INSERT INTO migration_probe (position) VALUES (2);",
        ),
        Migration::new(
            "0001_create_probe",
            "CREATE TABLE migration_probe (position INTEGER NOT NULL); INSERT INTO migration_probe (position) VALUES (1);",
        ),
    ];

    apply_migrations(&database, &migrations)?;

    let connection = Connection::open(database)?;
    let positions = connection
        .prepare("SELECT position FROM migration_probe ORDER BY rowid")?
        .query_map([], |row| row.get::<_, i64>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    let versions = connection
        .prepare("SELECT version FROM schema_migrations ORDER BY version")?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;

    assert_eq!(positions, vec![1_i64, 2]);
    assert_eq!(
        versions,
        vec![
            "0001_create_probe".to_owned(),
            "0002_insert_second".to_owned(),
        ]
    );
    Ok(())
}

#[test]
fn rerun_is_idempotent() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("desktop.sqlite3");
    let migrations = [Migration::new(
        "0001_create_probe",
        "CREATE TABLE migration_probe (value TEXT NOT NULL); INSERT INTO migration_probe (value) VALUES ('installed');",
    )];

    apply_migrations(&database, &migrations)?;
    Connection::open(&database)?.execute(
        "INSERT INTO migration_probe (value) VALUES ('user-owned')",
        [],
    )?;
    apply_migrations(&database, &migrations)?;

    let connection = Connection::open(database)?;
    assert_eq!(
        connection.query_row("SELECT COUNT(*) FROM migration_probe", [], |row| row
            .get::<_, i64>(0))?,
        2_i64
    );
    assert_eq!(
        connection.query_row("SELECT COUNT(*) FROM schema_migrations", [], |row| row
            .get::<_, i64>(0))?,
        1_i64
    );
    Ok(())
}

#[test]
fn existing_replay_schema_upgrades_without_losing_rows() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("offline-replay.sqlite3");
    let connection = Connection::open(&database)?;
    connection.execute_batch(
        "CREATE TABLE offline_replay_mutations (
             sequence INTEGER PRIMARY KEY AUTOINCREMENT CHECK (sequence > 0),
             entity_id TEXT NOT NULL,
             payload BLOB NOT NULL
         ) STRICT;
         CREATE TABLE offline_replay_conflicts (
             sequence INTEGER PRIMARY KEY REFERENCES offline_replay_mutations(sequence) ON DELETE CASCADE,
             entity_id TEXT NOT NULL,
             reason_code TEXT NOT NULL
         ) STRICT;
         INSERT INTO offline_replay_mutations (entity_id, payload) VALUES ('estimate-1', X'7B7D');",
    )?;
    drop(connection);

    let store = ReplayStore::open(&database)?;

    assert_eq!(
        store.pending()?,
        vec![Mutation {
            sequence: 1,
            entity_id: "estimate-1".to_owned(),
            payload: br"{}".to_vec(),
        }]
    );
    assert_eq!(
        Connection::open(database)?.query_row(
            "SELECT COUNT(*) FROM schema_migrations",
            [],
            |row| row.get::<_, i64>(0),
        )?,
        1_i64
    );
    Ok(())
}

#[test]
fn rejects_checksum_drift_for_an_applied_migration() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("desktop.sqlite3");
    let original = [Migration::new(
        "0001_create_probe",
        "CREATE TABLE migration_probe (value TEXT NOT NULL);",
    )];
    let changed = [Migration::new(
        "0001_create_probe",
        "CREATE TABLE migration_probe (value TEXT NOT NULL, changed INTEGER NOT NULL);",
    )];

    apply_migrations(&database, &original)?;

    assert!(matches!(
        apply_migrations(&database, &changed),
        Err(MigrationError::ChecksumDrift { version, .. }) if version == "0001_create_probe"
    ));
    assert_eq!(
        Connection::open(database)?.query_row(
            "SELECT COUNT(*) FROM schema_migrations",
            [],
            |row| row.get::<_, i64>(0),
        )?,
        1_i64
    );
    Ok(())
}

#[test]
fn rolls_back_all_migrations_when_a_statement_fails() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("desktop.sqlite3");
    let migrations = [
        Migration::new(
            "0001_create_first",
            "CREATE TABLE first_table (id INTEGER PRIMARY KEY);",
        ),
        Migration::new(
            "0002_fail_after_write",
            "CREATE TABLE second_table (id INTEGER PRIMARY KEY); INSERT INTO missing_table (id) VALUES (1);",
        ),
    ];

    assert!(matches!(
        apply_migrations(&database, &migrations),
        Err(MigrationError::Sqlite(_))
    ));

    let connection = Connection::open(database)?;
    assert!(!table_exists(&connection, "first_table")?);
    assert!(!table_exists(&connection, "second_table")?);
    assert!(!table_exists(&connection, "schema_migrations")?);
    Ok(())
}

#[test]
fn concurrent_startup_applies_each_migration_once() -> Result<(), Box<dyn Error>> {
    const MIGRATIONS: [Migration; 2] = [
        Migration::new(
            "0001_create_probe",
            "CREATE TABLE migration_probe (version TEXT NOT NULL); INSERT INTO migration_probe (version) VALUES ('0001');",
        ),
        Migration::new(
            "0002_insert_probe",
            "INSERT INTO migration_probe (version) VALUES ('0002');",
        ),
    ];

    let temporary = tempdir()?;
    let database = Arc::new(temporary.path().join("desktop.sqlite3"));
    let workers = 6;
    let barrier = Arc::new(Barrier::new(workers));
    let handles = (0..workers)
        .map(|_| {
            let database = Arc::clone(&database);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                apply_migrations(database.as_path(), &MIGRATIONS)
            })
        })
        .collect::<Vec<_>>();

    for handle in handles {
        match handle.join() {
            Ok(result) => result?,
            Err(_) => return Err("migration worker panicked".into()),
        }
    }

    let connection = Connection::open(database.as_path())?;
    assert_eq!(
        connection.query_row("SELECT COUNT(*) FROM migration_probe", [], |row| row
            .get::<_, i64>(0))?,
        2_i64
    );
    assert_eq!(
        connection.query_row("SELECT COUNT(*) FROM schema_migrations", [], |row| row
            .get::<_, i64>(0))?,
        2_i64
    );
    Ok(())
}

fn table_exists(connection: &Connection, name: &str) -> Result<bool, rusqlite::Error> {
    connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1)",
        [name],
        |row| row.get::<_, bool>(0),
    )
}
