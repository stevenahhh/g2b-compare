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
from .estimate_models import BundleCandidate as _BundleCandidate
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
        if item.view.company != baseline.view.company
        and item.view.price_won >= baseline.view.price_won
    )
    if not eligible:
        return ()
    chosen: list[_MainCandidate] = []
    companies = {baseline.view.company}
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
        for item in eligible:
            choose(item, percentage)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
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
                item.view.price_won,
                item.source_row,
                item.view.company.encode("utf-8"),
                item.view.product_id,
            ),
        )
    )


def choose_bundle_alternatives(
    bundles: tuple[_BundleCandidate, ...],
    selected: _BundleCandidate,
    *,
    distinct_product_ids: bool = False,
) -> tuple[_BundleCandidate, ...]:
    """Choose the two cheapest complete company-distinct bundles above A."""
    return rank_bundle_alternatives(
        bundles,
        selected,
        distinct_product_ids=distinct_product_ids,
    )[:ALTERNATIVE_COUNT]


def rank_bundle_alternatives(
    bundles: tuple[_BundleCandidate, ...],
    selected: _BundleCandidate,
    *,
    distinct_product_ids: bool = False,
) -> tuple[_BundleCandidate, ...]:
    """Rank each company's cheapest complete eligible bundle."""
    by_company: dict[str, _BundleCandidate] = {}
    for bundle in bundles:
        if bundle.main.view.company == selected.main.view.company:
            continue
        if bundle.main.view.price_won < selected.main.view.price_won:
            continue
        if bundle.total_price_won < selected.total_price_won:
            continue
        if (
            distinct_product_ids
            and bundle.main.view.product_id == selected.main.view.product_id
        ):
            continue
        current = by_company.get(bundle.main.view.company)
        key = (
            bundle.total_price_won - selected.total_price_won,
            bundle.main.key[:5],
            bundle.main.source_row,
            bundle.main.view.product_id,
        )
        if current is None or key < (
            current.total_price_won - selected.total_price_won,
            current.main.key[:5],
            current.main.source_row,
            current.main.view.product_id,
        ):
            by_company[bundle.main.view.company] = bundle
    return tuple(
        sorted(
            by_company.values(),
            key=lambda bundle: (
                bundle.total_price_won - selected.total_price_won,
                bundle.main.key[:5],
                bundle.main.source_row,
                bundle.main.view.company.encode("utf-8"),
                bundle.main.view.product_id,
            ),
        )
    )


def selected_main(
    ranked: tuple[_MainCandidate, ...],
    line: EstimateLine,
) -> _MainCandidate | None:
    """Return the candidate representing the product selected into slot A."""
    return next(
        (
            item
            for item in ranked
            if item.view.product_id == line.product_id
            and item.view.company == line.company_snapshot
        ),
        None,
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
    if _line_component(line) != "switch":
        return False
    requirements = _option_requirements("switch", line.spec_snapshot)
    if "ports:24" in requirements and line.quantity > 1:
        return True
    if "ports:8" not in requirements or line.quantity > 1:
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
