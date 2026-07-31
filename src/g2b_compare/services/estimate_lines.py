"""Transactional estimate line operations."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query

from .estimate_drafts import require_draft, touch
from .estimate_models import (
    EstimateFullError,
    EstimateLine,
    EstimateLineInput,
    EstimateNotFoundError,
)
from .estimate_store_records import read_line, require_quantity

if TYPE_CHECKING:
    from pathlib import Path


def add_line(
    database: Path,
    max_lines: int,
    estimate_id: str,
    item: EstimateLineInput,
) -> EstimateLine:
    """Append a snapshot or merge an identical verified option relation."""
    require_quantity(item.quantity)
    with connect(database) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        require_draft(connection, estimate_id)
        if item.relation_id is not None:
            existing = query(
                connection,
                """
                SELECT id, quantity FROM estimate_lines
                WHERE estimate_id = ? AND relation_id = ?
                """,
                (estimate_id, item.relation_id),
            ).fetchone()
            if existing is not None:
                line_id = as_text(existing[0])
                quantity = Decimal(str(existing[1])) + item.quantity
                _ = query(
                    connection,
                    "UPDATE estimate_lines SET quantity = ? WHERE id = ?",
                    (str(quantity), line_id),
                )
                touch(connection, estimate_id)
                line = read_line(connection, line_id)
                _ = connection.commit()
                return line
        count_row = query(
            connection,
            "SELECT COUNT(*) FROM estimate_lines WHERE estimate_id = ?",
            (estimate_id,),
        ).fetchone()
        if count_row is None or as_int(count_row[0]) >= max_lines:
            raise EstimateFullError(estimate_id)
        line_id = uuid4().hex
        line_no = as_int(count_row[0]) + 1
        _ = query(
            connection,
            """
            INSERT INTO estimate_lines VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                line_id,
                estimate_id,
                line_no,
                item.line_kind,
                item.product_id,
                item.parent_product_id,
                item.relation_id,
                item.offer_operation,
                item.offer_key,
                item.item_name_snapshot,
                item.spec_snapshot,
                item.company_snapshot,
                item.unit_snapshot,
                item.unit_price_won_snapshot,
                str(item.quantity),
            ),
        )
        touch(connection, estimate_id)
        line = read_line(connection, line_id)
        _ = connection.commit()
        return line


def update_quantity(
    database: Path,
    estimate_id: str,
    line_id: str,
    quantity: Decimal,
) -> EstimateLine:
    """Update one positive quantity without changing its snapshots."""
    require_quantity(quantity)
    with connect(database) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        require_draft(connection, estimate_id)
        cursor = query(
            connection,
            """
            UPDATE estimate_lines SET quantity = ?
            WHERE id = ? AND estimate_id = ?
            """,
            (str(quantity), line_id, estimate_id),
        )
        if cursor.rowcount != 1:
            raise EstimateNotFoundError(line_id)
        touch(connection, estimate_id)
        line = read_line(connection, line_id)
        _ = connection.commit()
        return line


def delete_line(database: Path, estimate_id: str, line_id: str) -> None:
    """Delete one line and close its visible line-number gap."""
    with connect(database) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        require_draft(connection, estimate_id)
        found = query(
            connection,
            "SELECT line_no FROM estimate_lines WHERE id = ? AND estimate_id = ?",
            (line_id, estimate_id),
        ).fetchone()
        if found is None:
            raise EstimateNotFoundError(line_id)
        line_no = as_int(found[0])
        _ = query(connection, "DELETE FROM estimate_lines WHERE id = ?", (line_id,))
        _ = query(
            connection,
            """
            UPDATE estimate_lines SET line_no = line_no - 1
            WHERE estimate_id = ? AND line_no > ?
            """,
            (estimate_id, line_no),
        )
        touch(connection, estimate_id)
        _ = connection.commit()
