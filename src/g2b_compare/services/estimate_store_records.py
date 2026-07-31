"""Typed row mapping for persisted estimate lines."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from g2b_compare.db.sql import SqlRow, SqlValue, as_int, as_text, query

from .estimate_models import EstimateLine, EstimateLineInput, EstimateNotFoundError

if TYPE_CHECKING:
    import sqlite3


def read_line(connection: sqlite3.Connection, line_id: str) -> EstimateLine:
    """Read one persisted estimate line."""
    row = query(
        connection,
        """
        SELECT id, line_no, line_kind, product_id, parent_product_id,
        relation_id, offer_operation, offer_key, item_name_snapshot,
        spec_snapshot, company_snapshot, unit_snapshot,
        unit_price_won_snapshot, quantity FROM estimate_lines WHERE id = ?
        """,
        (line_id,),
    ).fetchone()
    if row is None:
        raise EstimateNotFoundError(line_id)
    return line_from_row(row)


def document_line(
    line_id: str,
    line_no: int,
    item: EstimateLineInput,
) -> EstimateLine:
    """Convert one document input into its immutable snapshot."""
    return EstimateLine(
        id=line_id,
        line_no=line_no,
        line_kind=item.line_kind,
        product_id=item.product_id,
        parent_product_id=item.parent_product_id,
        relation_id=item.relation_id,
        offer_operation=item.offer_operation,
        offer_key=item.offer_key,
        item_name_snapshot=item.item_name_snapshot,
        spec_snapshot=item.spec_snapshot,
        company_snapshot=item.company_snapshot,
        unit_snapshot=item.unit_snapshot,
        unit_price_won_snapshot=item.unit_price_won_snapshot,
        quantity=item.quantity,
    )


def insert_line(
    connection: sqlite3.Connection,
    estimate_id: str,
    line: EstimateLine,
) -> None:
    """Insert one complete immutable line snapshot."""
    _ = query(
        connection,
        """
        INSERT INTO estimate_lines VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            line.id,
            estimate_id,
            line.line_no,
            line.line_kind,
            line.product_id,
            line.parent_product_id,
            line.relation_id,
            line.offer_operation,
            line.offer_key,
            line.item_name_snapshot,
            line.spec_snapshot,
            line.company_snapshot,
            line.unit_snapshot,
            line.unit_price_won_snapshot,
            str(line.quantity),
        ),
    )


def line_from_row(row: SqlRow) -> EstimateLine:
    """Map one typed SQLite row to an estimate line."""
    return EstimateLine(
        id=as_text(row[0]),
        line_no=as_int(row[1]),
        line_kind=_line_kind(as_text(row[2])),
        product_id=as_text(row[3]),
        parent_product_id=_optional_text(row[4]),
        relation_id=_optional_text(row[5]),
        offer_operation=_optional_text(row[6]),
        offer_key=_optional_text(row[7]),
        item_name_snapshot=as_text(row[8]),
        spec_snapshot=as_text(row[9]),
        company_snapshot=as_text(row[10]),
        unit_snapshot=as_text(row[11]),
        unit_price_won_snapshot=as_int(row[12]),
        quantity=Decimal(str(row[13])),
    )


def require_quantity(quantity: Decimal) -> None:
    """Require a finite positive quantity."""
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(quantity)


def _optional_text(value: SqlValue) -> str | None:
    return None if value is None else as_text(value)


def _line_kind(value: str) -> Literal["main", "option"]:
    if value == "main":
        return "main"
    if value == "option":
        return "option"
    raise EstimateNotFoundError(value)
