"""Persist and validate pinned A/B/C comparison snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import (
    COMPARISON_SLOT_COUNT,
    ComparisonView,
)
from .estimate_policy import (
    requires_distinct_product_ids as _requires_distinct_product_ids,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine


def insert_comparisons(
    connection: sqlite3.Connection,
    line: EstimateLine,
    comparisons: tuple[ComparisonView, ...],
) -> None:
    """Persist an already selected, slot-aligned comparison projection."""
    _ = connection.executemany(
        "INSERT INTO estimate_comparisons VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (
                line.id,
                slot,
                item.product_id,
                item.relation_id,
                item.company,
                item.spec,
                item.price_won,
            )
            for slot, item in zip(("A", "B", "C"), comparisons, strict=False)
        ),
    )


def has_comparisons(connection: sqlite3.Connection, line: EstimateLine) -> bool:
    """Return whether one line already has a valid complete comparison set."""
    rows = query(
        connection,
        """
        SELECT slot, product_id, relation_id, company_snapshot,
               spec_snapshot, price_won_snapshot
        FROM estimate_comparisons WHERE estimate_line_id = ? ORDER BY slot
        """,
        (line.id,),
    ).fetchall()
    if len(rows) != COMPARISON_SLOT_COUNT or as_text(rows[0][0]) != "A":
        return False
    product_ids = [as_text(row[1]) for row in rows]
    companies = [as_text(row[3]) for row in rows]
    return (
        product_ids[0] == line.product_id
        and (None if rows[0][2] is None else as_text(rows[0][2])) == line.relation_id
        and companies[0] == line.company_snapshot
        and as_text(rows[0][4]) == line.spec_snapshot
        and as_int(rows[0][5]) == line.unit_price_won_snapshot
        and len(companies) == len(set(companies))
        and (
            not _requires_distinct_product_ids(connection, line)
            or len(product_ids) == len(set(product_ids))
        )
    )
