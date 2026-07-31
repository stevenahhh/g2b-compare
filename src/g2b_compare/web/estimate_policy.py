"""Comparison eligibility and price-ladder policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_text, query

from .estimate_features import (
    line_component as _line_component,
)
from .estimate_features import (
    option_requirements as _option_requirements,
)
from .estimate_models import (
    ALTERNATIVE_COUNT,
    KOREANET_COMPANY,
    PRICE_LADDER_PERCENTAGES,
)
from .estimate_models import (
    MainCandidate as _MainCandidate,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine


def choose_main_alternatives(  # noqa: C901
    ranked: tuple[_MainCandidate, ...],
    baseline: _MainCandidate | None,
    *,
    distinct_product_ids: bool = False,
) -> tuple[_MainCandidate, ...]:
    """Choose company-distinct alternatives on the configured price ladder."""
    if baseline is None:
        return ()
    eligible = tuple(
        item
        for item in ranked
        if item.view.company != KOREANET_COMPANY
        and item.view.price_won >= baseline.view.price_won
    )
    if not eligible:
        return ()
    best_compatibility = eligible[0].key[:5]
    preferred = tuple(item for item in eligible if item.key[:5] == best_compatibility)
    chosen: list[_MainCandidate] = []
    companies = {KOREANET_COMPANY}
    product_ids = {baseline.view.product_id}

    def choose(item: _MainCandidate, percentage: int | None) -> None:
        if item.view.company in companies:
            return
        if distinct_product_ids and item.view.product_id in product_ids:
            return
        if percentage is not None and not within_price_limit(
            baseline.view.price_won, item.view.price_won, percentage
        ):
            return
        chosen.append(item)
        companies.add(item.view.company)
        product_ids.add(item.view.product_id)

    for percentage in PRICE_LADDER_PERCENTAGES:
        for item in preferred:
            choose(item, percentage)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
        if len(chosen) == ALTERNATIVE_COUNT:
            break
    if len(chosen) < ALTERNATIVE_COUNT:
        for item in preferred:
            choose(item, None)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
    if len(chosen) < ALTERNATIVE_COUNT:
        for item in eligible:
            choose(item, None)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
    return tuple(
        sorted(
            chosen,
            key=lambda item: (
                item.source_row,
                item.view.company.encode("utf-8"),
                item.view.product_id,
            ),
        )
    )


def koreanet_main(ranked: tuple[_MainCandidate, ...]) -> _MainCandidate | None:
    """Return the KoreaNet baseline candidate when available."""
    return next(
        (item for item in ranked if item.view.company == KOREANET_COMPANY),
        None,
    )


def requires_distinct_product_ids(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> bool:
    """Require distinct product identities for sensitive 8-port switches."""
    if _line_component(line) != "switch" or "ports:8" not in _option_requirements(
        "switch", line.spec_snapshot
    ):
        return False
    if line.line_kind == "main":
        return True
    row = query(
        connection,
        "SELECT contract_method FROM priority_products WHERE product_id = ?",
        (line.parent_product_id,),
    ).fetchone()
    return row is None or as_text(row[0]) != "다수공급자계약"


def within_price_limit(baseline: int, candidate: int, percentage: int) -> bool:
    """Return whether a candidate is within a percentage above baseline."""
    return candidate * 100 <= baseline * (100 + percentage)
