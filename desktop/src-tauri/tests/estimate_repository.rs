use std::{
    error::Error,
    path::PathBuf,
    sync::{Arc, Barrier},
    thread,
};

use g2b_compare_desktop_lib::db::MigrationError;
use g2b_compare_desktop_lib::estimate::{
    CreateEstimate, EstimateComparisonInput, EstimateError, EstimateLineInput, EstimateRepository,
    UpdateEstimate,
};
use rusqlite::Connection;
use tempfile::tempdir;

const REVISION_MIGRATION_VERSION: &str = "desktop_0001_estimate_draft_revision";
const REVISION_MIGRATION_SHA256: &str =
    "caf907ce2347bc676b9f02bc058ea9d6277b9266c6fb1647ffd272db3d067339";

#[test]
fn creates_reads_updates_and_deletes_a_document_with_lines_and_comparisons()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    let repository = EstimateRepository::open(&database)?;

    let created = repository.create(CreateEstimate {
        id: "0123456789abcdef0123456789abcdef".into(),
        title: "현장 내역서".into(),
        template_sha256: "a".repeat(64),
        lines: vec![main_line("line-main"), option_line("line-option")],
        comparisons: vec![
            comparison("line-main", "A", "10000001"),
            comparison("line-main", "B", "10000002"),
            comparison("line-main", "C", "10000003"),
        ],
    })?;
    assert_eq!(created.revision, 1);
    assert_eq!(created.lines.len(), 2);
    assert_eq!(created.lines[1].line_no, 2);
    assert_eq!(created.lines[0].comparisons.len(), 3);

    let read = repository.read("0123456789abcdef0123456789abcdef")?;
    assert_eq!(read.title, "현장 내역서");
    assert_eq!(read.lines[0].item_name_snapshot, "주 품목 스냅샷");
    assert_eq!(read.lines[1].relation_id.as_deref(), Some("relation-1"));
    assert_eq!(read.lines[0].comparisons[2].slot, "C");

    let updated = repository.update(
        "0123456789abcdef0123456789abcdef",
        UpdateEstimate {
            expected_revision: read.revision,
            title: "수정된 내역서".into(),
            lines: vec![main_line("line-main")],
            comparisons: vec![comparison("line-main", "A", "10000009")],
        },
    )?;
    assert_eq!(updated.revision, 2);
    assert_eq!(updated.title, "수정된 내역서");
    assert_eq!(updated.lines.len(), 1);
    assert_eq!(updated.lines[0].quantity, "1");
    assert_eq!(updated.lines[0].comparisons[0].product_id, "10000009");

    repository.delete("0123456789abcdef0123456789abcdef")?;
    assert!(matches!(
        repository.read("0123456789abcdef0123456789abcdef"),
        Err(EstimateError::NotFound { .. })
    ));
    let connection = Connection::open(&database)?;
    assert_eq!(count(&connection, "estimate_lines")?, 0);
    assert_eq!(count(&connection, "estimate_comparisons")?, 0);
    Ok(())
}

#[test]
fn rejects_a_stale_revision_without_mutating_the_saved_document() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    let repository = EstimateRepository::open(&database)?;
    let created = repository.create(CreateEstimate {
        id: "0123456789abcdef0123456789abcdef".into(),
        title: "원본".into(),
        template_sha256: "b".repeat(64),
        lines: vec![main_line("line-main")],
        comparisons: vec![],
    })?;

    let first = repository.update(
        &created.id,
        UpdateEstimate {
            expected_revision: created.revision,
            title: "첫 번째 저장".into(),
            lines: vec![main_line("line-main")],
            comparisons: vec![],
        },
    )?;
    assert!(matches!(
        repository.update(
            &created.id,
            UpdateEstimate {
                expected_revision: created.revision,
                title: "过时的保存".into(),
                lines: vec![main_line("line-main")],
                comparisons: vec![],
            },
        ),
        Err(EstimateError::RevisionConflict {
            expected: 1,
            actual: 2,
        })
    ));
    let unchanged = repository.read(&created.id)?;
    assert_eq!(unchanged.revision, first.revision);
    assert_eq!(unchanged.title, "첫 번째 저장");
    assert_eq!(unchanged.lines[0].quantity, "1");
    Ok(())
}

#[test]
fn concurrent_opens_upgrade_a_legacy_database_once_without_losing_drafts()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = Arc::new(temporary.path().join("estimates.sqlite3"));
    create_estimate_schema(database.as_path())?;
    let connection = Connection::open(database.as_path())?;
    connection.execute(
        "INSERT INTO estimate_drafts (id, title, template_sha256, created_at, updated_at)
         VALUES ('legacy-draft', '보존되어야 하는 기존 내역서', ?1, '2026-08-04T00:00:00Z', '2026-08-04T00:00:00Z')",
        ["f".repeat(64)],
    )?;
    connection.execute(
        "INSERT INTO estimate_lines (
             id, estimate_id, line_no, line_kind, product_id, parent_product_id, relation_id,
             offer_operation, offer_key, item_name_snapshot, spec_snapshot, company_snapshot,
             unit_snapshot, unit_price_won_snapshot, quantity
         ) VALUES (
             'legacy-line', 'legacy-draft', 1, 'main', '10000001', NULL, NULL, NULL, NULL,
             '기존 품목', '기존 규격', '기존 회사', '개', 1000, '1'
         )",
        [],
    )?;
    drop(connection);

    let repositories = open_repositories_concurrently(&database)?;
    assert_eq!(repositories.len(), 2);
    for repository in repositories {
        assert_eq!(repository.list()?.len(), 1);
    }

    let connection = Connection::open(database.as_path())?;
    assert_eq!(
        connection.query_row(
            "SELECT id, title, revision FROM estimate_drafts WHERE id = 'legacy-draft'",
            [],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            },
        )?,
        (
            "legacy-draft".to_owned(),
            "보존되어야 하는 기존 내역서".to_owned(),
            1,
        )
    );
    assert_eq!(count(&connection, "estimate_lines")?, 1);
    assert_revision_migration_entry(&connection)?;
    Ok(())
}

#[test]
fn concurrent_opens_adopt_a_preledger_revision_column_once_without_losing_drafts()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = Arc::new(temporary.path().join("estimates.sqlite3"));
    create_estimate_schema(database.as_path())?;
    let connection = Connection::open(database.as_path())?;
    connection.execute_batch(
        "ALTER TABLE estimate_drafts
         ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
         INSERT INTO estimate_drafts (id, title, template_sha256, created_at, updated_at)
         VALUES (
             'preledger-draft', '기존 버전 열이 있는 내역서',
             'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
             '2026-08-04T00:00:00Z', '2026-08-04T00:00:00Z'
         );
         INSERT INTO estimate_lines (
             id, estimate_id, line_no, line_kind, product_id, parent_product_id, relation_id,
             offer_operation, offer_key, item_name_snapshot, spec_snapshot, company_snapshot,
             unit_snapshot, unit_price_won_snapshot, quantity
         ) VALUES (
             'preledger-line', 'preledger-draft', 1, 'main', '10000001', NULL, NULL, NULL, NULL,
             '기존 품목', '기존 규격', '기존 회사', '개', 1000, '1'
         );",
    )?;
    drop(connection);

    let repositories = open_repositories_concurrently(&database)?;
    assert_eq!(repositories.len(), 2);
    for repository in repositories {
        assert_eq!(repository.list()?.len(), 1);
    }

    let connection = Connection::open(database.as_path())?;
    assert_eq!(
        connection.query_row(
            "SELECT id, title, revision FROM estimate_drafts WHERE id = 'preledger-draft'",
            [],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            },
        )?,
        (
            "preledger-draft".to_owned(),
            "기존 버전 열이 있는 내역서".to_owned(),
            1,
        )
    );
    assert_eq!(count(&connection, "estimate_lines")?, 1);
    assert_revision_migration_entry(&connection)?;
    Ok(())
}

#[test]
fn incompatible_preledger_revision_column_fails_closed_without_a_ledger_entry()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    Connection::open(&database)?.execute_batch(
        "ALTER TABLE estimate_drafts
         ADD COLUMN revision TEXT NOT NULL DEFAULT '1';",
    )?;

    assert!(matches!(
        EstimateRepository::open(&database),
        Err(EstimateError::Migration(MigrationError::IncompatibleSchema { version, .. }))
            if version == REVISION_MIGRATION_VERSION
    ));
    let connection = Connection::open(database)?;
    assert!(!connection.query_row(
        "SELECT EXISTS(
             SELECT 1 FROM sqlite_master
             WHERE type = 'table' AND name = 'schema_migrations'
         )",
        [],
        |row| row.get::<_, bool>(0),
    )?);
    Ok(())
}

#[test]
fn rejects_noncanonical_quantities_at_every_persistence_boundary() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    let repository = EstimateRepository::open(&database)?;

    for quantity in ["2", "abc", "1e999"] {
        assert!(matches!(
            repository.create(CreateEstimate {
                id: format!("invalid-{quantity}"),
                title: "유효하지 않은 수량".into(),
                template_sha256: "d".repeat(64),
                lines: vec![main_line_with_quantity("line-main", quantity)],
                comparisons: vec![],
            }),
            Err(EstimateError::InvalidQuantity)
        ));
    }
    let connection = Connection::open(&database)?;
    assert_eq!(count(&connection, "estimate_drafts")?, 0);
    assert_eq!(count(&connection, "estimate_lines")?, 0);
    drop(connection);

    let created = repository.create(CreateEstimate {
        id: "0123456789abcdef0123456789abcdef".into(),
        title: "원본".into(),
        template_sha256: "d".repeat(64),
        lines: vec![main_line("line-main")],
        comparisons: vec![],
    })?;
    assert!(matches!(
        repository.update(
            &created.id,
            UpdateEstimate {
                expected_revision: created.revision,
                title: "유효하지 않은 저장".into(),
                lines: vec![main_line_with_quantity("line-main", "2")],
                comparisons: vec![],
            },
        ),
        Err(EstimateError::InvalidQuantity)
    ));
    assert!(matches!(
        repository.append_line(&created.id, &main_line_with_quantity("line-invalid", "abc"),),
        Err(EstimateError::InvalidQuantity)
    ));
    let unchanged = repository.read(&created.id)?;
    assert_eq!(unchanged.revision, created.revision);
    assert_eq!(unchanged.lines.len(), 1);
    assert_eq!(unchanged.lines[0].quantity, "1");
    Ok(())
}

#[test]
fn legacy_quantity_does_not_change_the_applied_price_total() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    let repository = EstimateRepository::open(&database)?;
    let created = repository.create(CreateEstimate {
        id: "0123456789abcdef0123456789abcdef".into(),
        title: "기존 수량".into(),
        template_sha256: "e".repeat(64),
        lines: vec![main_line("line-main")],
        comparisons: vec![
            comparison("line-main", "A", "10000001"),
            comparison("line-main", "B", "10000002"),
            comparison("line-main", "C", "10000003"),
        ],
    })?;
    let connection = Connection::open(&database)?;
    connection.execute(
        "UPDATE estimate_lines SET quantity = '2' WHERE estimate_id = ?1",
        [&created.id],
    )?;
    drop(connection);

    let document = repository.read(&created.id)?;
    let detail_total = document
        .lines
        .iter()
        .map(|line| {
            line.comparisons
                .iter()
                .find(|comparison| comparison.slot == "A")
                .map_or(line.unit_price_won_snapshot, |comparison| {
                    comparison.price_won_snapshot
                })
        })
        .sum::<i64>();
    let summaries = repository.list()?;

    assert_eq!(document.lines[0].quantity, "1");
    assert_eq!(detail_total, 900);
    assert_eq!(summaries[0].total_won, detail_total);
    Ok(())
}

#[test]
fn rolls_back_header_lines_and_comparisons_when_one_write_fails() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let database = temporary.path().join("estimates.sqlite3");
    create_estimate_schema(&database)?;
    let repository = EstimateRepository::open(&database)?;
    let created = repository.create(CreateEstimate {
        id: "0123456789abcdef0123456789abcdef".into(),
        title: "원본".into(),
        template_sha256: "c".repeat(64),
        lines: vec![main_line("line-main")],
        comparisons: vec![comparison("line-main", "A", "10000001")],
    })?;

    let result = repository.update(
        &created.id,
        UpdateEstimate {
            expected_revision: created.revision,
            title: "절대 저장되면 안 됨".into(),
            lines: vec![main_line("line-main"), option_line("line-option")],
            comparisons: vec![
                comparison("line-main", "A", "10000002"),
                comparison("line-main", "A", "10000003"),
            ],
        },
    );
    assert!(matches!(result, Err(EstimateError::Constraint { .. })));

    let unchanged = repository.read(&created.id)?;
    assert_eq!(unchanged.revision, created.revision);
    assert_eq!(unchanged.title, "원본");
    assert_eq!(unchanged.lines.len(), 1);
    assert_eq!(unchanged.lines[0].comparisons[0].product_id, "10000001");
    Ok(())
}

fn open_repositories_concurrently(
    database: &Arc<PathBuf>,
) -> Result<Vec<EstimateRepository>, Box<dyn Error>> {
    let workers = 2;
    let barrier = Arc::new(Barrier::new(workers));
    let handles = (0..workers)
        .map(|_| {
            let database = Arc::clone(database);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                EstimateRepository::open(database.as_path())
            })
        })
        .collect::<Vec<_>>();

    let mut repositories = Vec::with_capacity(workers);
    for handle in handles {
        match handle.join() {
            Ok(repository) => repositories.push(repository?),
            Err(_) => return Err("estimate repository open worker panicked".into()),
        }
    }
    Ok(repositories)
}

fn assert_revision_migration_entry(connection: &Connection) -> Result<(), Box<dyn Error>> {
    let ledger_entries = connection
        .prepare(
            "SELECT version, source_sha FROM schema_migrations
             WHERE version = ?1",
        )?
        .query_map([REVISION_MIGRATION_VERSION], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(
        ledger_entries,
        vec![(
            REVISION_MIGRATION_VERSION.to_owned(),
            REVISION_MIGRATION_SHA256.to_owned(),
        )]
    );
    Ok(())
}

fn create_estimate_schema(path: &std::path::Path) -> Result<(), rusqlite::Error> {
    let connection = Connection::open(path)?;
    connection.execute_batch(
        "PRAGMA foreign_keys = ON;
         CREATE TABLE estimate_drafts (
             id TEXT PRIMARY KEY,
             title TEXT NOT NULL,
             template_sha256 TEXT NOT NULL,
             created_at TEXT NOT NULL,
             updated_at TEXT NOT NULL
         );
         CREATE TABLE estimate_lines (
             id TEXT PRIMARY KEY,
             estimate_id TEXT NOT NULL REFERENCES estimate_drafts(id) ON DELETE CASCADE,
             line_no INTEGER NOT NULL,
             line_kind TEXT NOT NULL,
             product_id TEXT NOT NULL,
             parent_product_id TEXT,
             relation_id TEXT,
             offer_operation TEXT,
             offer_key TEXT,
             item_name_snapshot TEXT NOT NULL,
             spec_snapshot TEXT NOT NULL,
             company_snapshot TEXT NOT NULL,
             unit_snapshot TEXT NOT NULL,
             unit_price_won_snapshot INTEGER NOT NULL,
             quantity NUMERIC NOT NULL
         );
         CREATE TABLE priority_products (
             product_id TEXT PRIMARY KEY,
             detail_url TEXT NOT NULL
         );
         CREATE TABLE estimate_comparisons (
             estimate_line_id TEXT NOT NULL REFERENCES estimate_lines(id) ON DELETE CASCADE,
             slot TEXT NOT NULL,
             product_id TEXT NOT NULL,
             relation_id TEXT,
             company_snapshot TEXT NOT NULL,
             spec_snapshot TEXT NOT NULL,
             price_won_snapshot INTEGER NOT NULL,
             PRIMARY KEY (estimate_line_id, slot)
         );",
    )
}

fn count(connection: &Connection, table: &str) -> Result<i64, rusqlite::Error> {
    connection.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
        row.get(0)
    })
}

fn main_line(id: &str) -> EstimateLineInput {
    main_line_with_quantity(id, "1")
}

fn main_line_with_quantity(id: &str, quantity: &str) -> EstimateLineInput {
    EstimateLineInput {
        id: id.into(),
        line_kind: "main".into(),
        product_id: "10000001".into(),
        parent_product_id: None,
        relation_id: None,
        offer_operation: Some("공고".into()),
        offer_key: Some("offer-main".into()),
        item_name_snapshot: "주 품목 스냅샷".into(),
        spec_snapshot: "규격 스냅샷".into(),
        company_snapshot: "회사 스냅샷".into(),
        unit_snapshot: "개".into(),
        unit_price_won_snapshot: 1000,
        quantity: quantity.into(),
    }
}

fn option_line(id: &str) -> EstimateLineInput {
    EstimateLineInput {
        id: id.into(),
        line_kind: "option".into(),
        product_id: "10000002".into(),
        parent_product_id: Some("10000001".into()),
        relation_id: Some("relation-1".into()),
        offer_operation: Some("공고".into()),
        offer_key: Some("offer-option".into()),
        item_name_snapshot: "선택 품목 스냅샷".into(),
        spec_snapshot: "선택 규격 스냅샷".into(),
        company_snapshot: "선택 회사 스냅샷".into(),
        unit_snapshot: "식".into(),
        unit_price_won_snapshot: 2000,
        quantity: "1".into(),
    }
}

fn comparison(line_id: &str, slot: &str, product_id: &str) -> EstimateComparisonInput {
    EstimateComparisonInput {
        estimate_line_id: line_id.into(),
        slot: slot.into(),
        product_id: product_id.into(),
        relation_id: None,
        company_snapshot: format!("비교 회사 {slot}"),
        spec_snapshot: format!("비교 규격 {slot}"),
        price_won_snapshot: 900,
    }
}
