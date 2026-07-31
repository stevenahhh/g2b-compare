"""Persist and validate pinned A/B/C comparison snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import (
    COMPARISON_SLOT_COUNT,
    KOREANET_COMPANY,
    PRICE_LADDER_PERCENTAGES,
    ComparisonView,
)
from .estimate_policy import (
    requires_distinct_product_ids as _requires_distinct_product_ids,
)
from .estimate_policy import (
    within_price_limit as _within_price_limit,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine


def insert_comparisons(  # noqa: C901
    connection: sqlite3.Connection,
    line: EstimateLine,
    alternatives: tuple[ComparisonView, ...],
) -> None:
    """Persist selected A/B/C comparison snapshots."""
    selected = ComparisonView(
        "",
        line.product_id,
        line.relation_id,
        line.company_snapshot,
        line.spec_snapshot,
        line.unit_price_won_snapshot,
    )
    pool = (selected, *alternatives)
    baseline = next(
        (item for item in pool if item.company == KOREANET_COMPANY),
        None,
    )
    if baseline is None:
        return
    comparisons: list[ComparisonView] = [baseline]
    companies = {baseline.company}
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    product_ids = {baseline.product_id}

    def append(item: ComparisonView, percentage: int | None) -> None:
        if item.company in companies or item.price_won < baseline.price_won:
            return
        if percentage is not None and not _within_price_limit(
            baseline.price_won, item.price_won, percentage
        ):
            return
        if requires_distinct_ids and item.product_id in product_ids:
            return
        comparisons.append(item)
        companies.add(item.company)
        product_ids.add(item.product_id)

    for percentage in PRICE_LADDER_PERCENTAGES:
        for item in pool:
            append(item, percentage)
            if len(comparisons) == COMPARISON_SLOT_COUNT:
                break
        if len(comparisons) == COMPARISON_SLOT_COUNT:
            break
    if len(comparisons) < COMPARISON_SLOT_COUNT:
        for item in pool:
            append(item, None)
            if len(comparisons) == COMPARISON_SLOT_COUNT:
                break
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
        SELECT slot, product_id, company_snapshot, price_won_snapshot
        FROM estimate_comparisons WHERE estimate_line_id = ? ORDER BY slot
        """,
        (line.id,),
    ).fetchall()
    if len(rows) != COMPARISON_SLOT_COUNT or as_text(rows[0][0]) != "A":
        return False
    product_ids = [as_text(row[1]) for row in rows]
    companies = [as_text(row[2]) for row in rows]
    baseline_price = as_int(rows[0][3])
    return (
        companies[0] == KOREANET_COMPANY
        and len(companies) == len(set(companies))
        and (
            not _requires_distinct_product_ids(connection, line)
            or len(product_ids) == len(set(product_ids))
        )
        and all(baseline_price <= as_int(row[3]) for row in rows[1:])
    )
