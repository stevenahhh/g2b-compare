"""Configured SQLite connection ownership."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final, final, override

from .sql import query

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

BUSY_TIMEOUT_MS: Final = 5_000


@final
class SQLiteConfigurationError(Exception):
    """A required per-connection SQLite setting was not applied."""

    setting: str
    expected: str
    actual: str

    def __init__(self, setting: str, expected: str, actual: str) -> None:
        """Initialize the mismatched setting receipt."""
        super().__init__(setting, expected, actual)
        self.setting = setting
        self.expected = expected
        self.actual = actual

    @override
    def __str__(self) -> str:
        return (
            f"SQLite setting {self.setting} must be {self.expected}, "
            f"found {self.actual}"
        )


@contextmanager
def connect(database: Path) -> Generator[sqlite3.Connection]:
    """Open one WAL connection with foreign keys and bounded lock waiting."""
    connection = sqlite3.connect(
        database,
        timeout=BUSY_TIMEOUT_MS / 1_000,
        isolation_level=None,
    )
    try:
        _ = connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        _ = connection.execute("PRAGMA foreign_keys = ON")
        journal_mode = query(connection, "PRAGMA journal_mode = WAL").fetchone()
        foreign_keys = query(connection, "PRAGMA foreign_keys").fetchone()
        busy_timeout = query(connection, "PRAGMA busy_timeout").fetchone()
        if journal_mode != ("wal",):
            raise SQLiteConfigurationError(
                setting="journal_mode",
                expected="wal",
                actual=str(journal_mode),
            )
        if foreign_keys != (1,):
            raise SQLiteConfigurationError(
                setting="foreign_keys",
                expected="1",
                actual=str(foreign_keys),
            )
        if busy_timeout != (BUSY_TIMEOUT_MS,):
            raise SQLiteConfigurationError(
                setting="busy_timeout",
                expected=str(BUSY_TIMEOUT_MS),
                actual=str(busy_timeout),
            )
        yield connection
    finally:
        connection.close()
