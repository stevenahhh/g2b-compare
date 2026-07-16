"""Gate startup on the required SQLite FTS5 capability."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Final, override

from g2b_compare.db.sql import query

FTS5_DISABLED: Final = "fts5-disabled"


class FTS5UnavailableError(Exception):
    """Stop startup when SQLite lacks the required ENABLE_FTS5 build option."""

    detail: str

    def __init__(self, detail: str = FTS5_DISABLED) -> None:
        """Initialize the stable startup failure identifier."""
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


def fts5_available() -> bool:
    """Return whether the runtime was compiled with ENABLE_FTS5."""
    with closing(sqlite3.connect(":memory:")) as connection:
        row = query(
            connection,
            "SELECT sqlite_compileoption_used('ENABLE_FTS5')",
        ).fetchone()
    return row == (1,)


def require_fts5(*, available: bool) -> None:
    """Apply the mandatory startup capability gate."""
    if not available:
        raise FTS5UnavailableError
