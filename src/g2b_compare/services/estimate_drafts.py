"""Estimate draft metadata persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import EstimateDraft, EstimateNotFoundError
from .estimate_store_records import line_from_row

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


def create_draft(database: Path, title: str, template_sha256: str) -> EstimateDraft:
    """Create one empty draft pinned to a template version."""
    estimate_id = uuid4().hex
    now = datetime.now(UTC).isoformat()
    with connect(database) as connection:
        _ = query(
            connection,
            "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
            (estimate_id, title, template_sha256, now, now),
        )
    return EstimateDraft(estimate_id, title, template_sha256, now, now, ())


def draft_count(database: Path) -> int:
    """Return the number used for the next visible draft sequence."""
    with connect(database) as connection:
        row = query(connection, "SELECT COUNT(*) FROM estimate_drafts").fetchone()
    return 0 if row is None else as_int(row[0])


def get_draft(database: Path, estimate_id: str) -> EstimateDraft:
    """Return one draft and its current ordered snapshots."""
    with connect(database) as connection:
        return read_draft(connection, estimate_id)


def read_draft(
    connection: sqlite3.Connection,
    estimate_id: str,
) -> EstimateDraft:
    """Return one draft inside an existing transaction."""
    row = query(
        connection,
        """
        SELECT id, title, template_sha256, created_at, updated_at
        FROM estimate_drafts WHERE id = ?
        """,
        (estimate_id,),
    ).fetchone()
    if row is None:
        raise EstimateNotFoundError(estimate_id)
    line_rows = query(
        connection,
        """
        SELECT id, line_no, line_kind, product_id, parent_product_id,
        relation_id, offer_operation, offer_key, item_name_snapshot,
        spec_snapshot, company_snapshot, unit_snapshot,
        unit_price_won_snapshot, quantity FROM estimate_lines
        WHERE estimate_id = ? ORDER BY line_no
        """,
        (estimate_id,),
    ).fetchall()
    return EstimateDraft(
        id=as_text(row[0]),
        title=as_text(row[1]),
        template_sha256=as_text(row[2]),
        created_at=as_text(row[3]),
        updated_at=as_text(row[4]),
        lines=tuple(line_from_row(item) for item in line_rows),
    )


def delete_draft_if_exists(database: Path, estimate_id: str) -> None:
    """Delete one document, succeeding when it is already absent."""
    with connect(database) as connection:
        _ = query(
            connection,
            "DELETE FROM estimate_drafts WHERE id = ?",
            (estimate_id,),
        )


def require_draft(connection: sqlite3.Connection, estimate_id: str) -> None:
    """Require one draft inside an existing transaction."""
    found = query(
        connection,
        "SELECT 1 FROM estimate_drafts WHERE id = ?",
        (estimate_id,),
    ).fetchone()
    if found is None:
        raise EstimateNotFoundError(estimate_id)


def touch(connection: sqlite3.Connection, estimate_id: str) -> None:
    """Advance a draft's update timestamp inside a transaction."""
    _ = query(
        connection,
        "UPDATE estimate_drafts SET updated_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), estimate_id),
    )
