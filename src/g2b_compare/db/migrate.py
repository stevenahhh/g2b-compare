"""Checksum-locked SQLite migration runner."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Final, final, override

from .connection import connect
from .sql import query

MIGRATION_DIRECTORY: Final = Path(__file__).with_name("migrations")


@final
class MigrationDriftError(Exception):
    """An applied migration no longer matches its immutable source."""

    version: str
    expected_sha: str
    actual_sha: str

    def __init__(self, version: str, expected_sha: str, actual_sha: str) -> None:
        """Initialize one immutable migration mismatch."""
        super().__init__(version, expected_sha, actual_sha)
        self.version = version
        self.expected_sha = expected_sha
        self.actual_sha = actual_sha

    @override
    def __str__(self) -> str:
        return (
            f"migration {self.version} checksum changed: "
            f"expected {self.expected_sha}, found {self.actual_sha}"
        )


def migrate(database: Path, migration_directory: Path = MIGRATION_DIRECTORY) -> None:
    """Apply every ordered SQL migration exactly once inside a transaction."""
    migrations = tuple(sorted(migration_directory.glob("*.sql")))
    with connect(database) as connection:
        _ = query(
            connection,
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                source_sha TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
        )
        for path in migrations:
            _apply_migration(connection, path)


def _apply_migration(connection: sqlite3.Connection, path: Path) -> None:
    source = path.read_bytes().replace(b"\r\n", b"\n")
    source_sha = hashlib.sha256(source).hexdigest()
    version = path.stem
    applied = query(
        connection,
        "SELECT source_sha FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    if applied is not None:
        if applied != (source_sha,):
            raise MigrationDriftError(
                version=version,
                expected_sha=str(applied[0]),
                actual_sha=source_sha,
            )
        return

    _ = connection.executescript(f"BEGIN IMMEDIATE;\n{source.decode('utf-8')}")
    try:
        _ = query(
            connection,
            """
            INSERT INTO schema_migrations(version, source_sha, applied_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (version, source_sha),
        )
        _ = query(connection, "COMMIT")
    except sqlite3.Error:
        _ = query(connection, "ROLLBACK")
        raise
