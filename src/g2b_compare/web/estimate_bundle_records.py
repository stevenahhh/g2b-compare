"""Read and validate persisted estimate bundle state."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.services import EstimateLine

from .estimate_records import has_comparisons

if TYPE_CHECKING:
    import sqlite3


def parent_line(
    connection: sqlite3.Connection,
    option: EstimateLine,
) -> EstimateLine | None:
    """Build the parent snapshot needed for a standalone option."""
    row = query(
        connection,
        """
        SELECT category_name, spec, company_name, unit, price_won
        FROM priority_products WHERE product_id = ?
        """,
        (option.parent_product_id,),
    ).fetchone()
    if row is None or option.parent_product_id is None:
        return None
    return EstimateLine(
        option.id,
        option.line_no,
        "main",
        option.parent_product_id,
        None,
        None,
        None,
        None,
        as_text(row[0]),
        as_text(row[1]),
        as_text(row[2]),
        as_text(row[3]),
        as_int(row[4]),
        option.quantity,
    )


def document_comparisons_are_valid(
    connection: sqlite3.Connection,
    lines: tuple[EstimateLine, ...],
) -> bool:
    """Check selected A identities and cross-row company alignment."""
    if not all(has_comparisons(connection, line) for line in lines):
        return False
    for main in (line for line in lines if line.line_kind == "main"):
        companies = _comparison_companies(connection, main.id)
        for option in (
            line
            for line in lines
            if line.line_kind == "option" and line.parent_product_id == main.product_id
        ):
            if _comparison_companies(connection, option.id) != companies:
                return False
    return True


def stored_document_lines(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[EstimateLine, ...]:
    """Load every persisted sibling needed for coherent reseeding."""
    rows = query(
        connection,
        """
        SELECT id, line_no, line_kind, product_id, parent_product_id,
               relation_id, offer_operation, offer_key, item_name_snapshot,
               spec_snapshot, company_snapshot, unit_snapshot,
               unit_price_won_snapshot, quantity
        FROM estimate_lines
        WHERE estimate_id = (
            SELECT estimate_id FROM estimate_lines WHERE id = ?
        )
        ORDER BY line_no
        """,
        (line.id,),
    ).fetchall()
    return tuple(
        EstimateLine(
            as_text(row[0]),
            as_int(row[1]),
            "main" if as_text(row[2]) == "main" else "option",
            as_text(row[3]),
            None if row[4] is None else as_text(row[4]),
            None if row[5] is None else as_text(row[5]),
            None if row[6] is None else as_text(row[6]),
            None if row[7] is None else as_text(row[7]),
            as_text(row[8]),
            as_text(row[9]),
            as_text(row[10]),
            as_text(row[11]),
            as_int(row[12]),
            Decimal(str(row[13])),
        )
        for row in rows
    )


def _comparison_companies(
    connection: sqlite3.Connection,
    line_id: str,
) -> tuple[str, ...]:
    return tuple(
        as_text(row[0])
        for row in query(
            connection,
            """
            SELECT company_snapshot FROM estimate_comparisons
            WHERE estimate_line_id = ? ORDER BY slot
            """,
            (line_id,),
        ).fetchall()
    )
