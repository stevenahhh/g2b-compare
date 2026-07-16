"""Inspect release ownership without mutating SQLite state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_text, query

if TYPE_CHECKING:
    import sqlite3


def materialization_is_active(
    connection: sqlite3.Connection,
    materialization_id: int,
) -> bool:
    """Return whether the exact materialization owns the active release."""
    tables = {
        as_text(row[0])
        for row in query(
            connection,
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        ).fetchall()
    }
    if not {"active_release", "release_bundles"}.issubset(tables):
        return False
    active = query(
        connection,
        """
        SELECT 1 FROM active_release
        JOIN release_bundles ON release_bundles.id = active_release.bundle_id
        WHERE release_bundles.materialization_id = ? LIMIT 1
        """,
        (materialization_id,),
    ).fetchone()
    return active is not None
