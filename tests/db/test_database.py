from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING

from g2b_compare.db.connection import BUSY_TIMEOUT_MS, connect
from g2b_compare.db.migrate import MIGRATION_DIRECTORY, migrate
from g2b_compare.db.sql import as_int, as_text, query

if TYPE_CHECKING:
    from pathlib import Path


def test_migration_is_idempotent_when_database_is_empty(tmp_path: Path) -> None:
    # Given: an empty temporary database
    database = tmp_path / "database.sqlite3"
    # When: the migration is applied twice
    migrate(database)
    migrate(database)
    # Then: one immutable receipt exists for every ordered migration
    with connect(database) as connection:
        row = query(
            connection,
            "SELECT COUNT(*), MIN(version) FROM schema_migrations",
        ).fetchone()
    assert row is not None
    assert (as_int(row[0]), as_text(row[1])) == (5, "0001_initial")


def test_migration_accepts_crlf_checkout(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for source in MIGRATION_DIRECTORY.glob("*.sql"):
        target = migrations / source.name
        target.write_bytes(
            source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )

    database = tmp_path / "database.sqlite3"
    migrate(database, MIGRATION_DIRECTORY)
    migrate(database, migrations)


def test_migration_accepts_legacy_crlf_receipts(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for source in MIGRATION_DIRECTORY.glob("*.sql"):
        target = migrations / source.name
        target.write_bytes(
            source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )

    database = tmp_path / "database.sqlite3"
    migrate(database, MIGRATION_DIRECTORY)
    with sqlite3.connect(database) as connection:
        for source in migrations.glob("*.sql"):
            legacy_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            _ = connection.execute(
                "UPDATE schema_migrations SET source_sha = ? WHERE version = ?",
                (legacy_sha, source.stem),
            )
        connection.commit()
    migrate(database, migrations)


def test_connection_applies_required_pragmas(tmp_path: Path) -> None:
    # Given: a migrated temporary database
    database = tmp_path / "database.sqlite3"
    migrate(database)
    # When: a repository connection is opened
    with connect(database) as connection:
        journal = query(connection, "PRAGMA journal_mode").fetchone()
        foreign_keys = query(connection, "PRAGMA foreign_keys").fetchone()
        busy_timeout = query(connection, "PRAGMA busy_timeout").fetchone()
    # Then: WAL, FK enforcement, and bounded waiting are active
    assert journal is not None
    assert as_text(journal[0]) == "wal"
    assert foreign_keys is not None
    assert as_int(foreign_keys[0]) == 1
    assert busy_timeout is not None
    assert as_int(busy_timeout[0]) == BUSY_TIMEOUT_MS
