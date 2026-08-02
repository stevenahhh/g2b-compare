"""Seed coherent persisted comparison bundles for estimate lines."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect

from .estimate_bundle_records import (
    document_comparisons_are_valid,
    parent_line,
    stored_document_lines,
)
from .estimate_comparison_reference import reference_document_comparisons
from .estimate_main_candidates import rank_main_candidates
from .estimate_models import (
    ALTERNATIVE_COUNT,
    BundleCandidate,
    ComparisonView,
    MainCandidate,
)
from .estimate_option_matching import match_bundle_option
from .estimate_option_pool import BundleOptionPools, load_bundle_option_pools
from .estimate_policy import (
    rank_bundle_alternatives,
    requires_distinct_product_ids,
)
from .estimate_records import insert_comparisons

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from g2b_compare.services import EstimateLine


@dataclass(frozen=True, slots=True)
class _BundleMatchContext:
    main: EstimateLine
    options: tuple[EstimateLine, ...]
    pools: BundleOptionPools
    option_cache: dict[
        tuple[str, str],
        tuple[ComparisonView, ...] | None,
    ] = field(default_factory=dict)


def seed_comparisons(database: Path, line: EstimateLine) -> None:
    """Pin comparisons for the complete document containing one line."""
    with connect(database) as connection:
        seed_comparisons_in_transaction(connection, line)


def seed_document_comparisons_in_transaction(
    connection: sqlite3.Connection,
    lines: tuple[EstimateLine, ...],
) -> None:
    """Seed every main and option from one coherent bundle plan."""
    if not lines:
        return
    referenced = reference_document_comparisons(lines)
    if referenced is None and document_comparisons_are_valid(connection, lines):
        return
    _ = connection.executemany(
        "DELETE FROM estimate_comparisons WHERE estimate_line_id = ?",
        ((line.id,) for line in lines),
    )
    if referenced is not None:
        for line, comparisons in zip(lines, referenced, strict=True):
            insert_comparisons(connection, line, comparisons)
        return
    pools = load_bundle_option_pools(connection)
    processed_options: set[str] = set()
    for main in (line for line in lines if line.line_kind == "main"):
        options = tuple(
            line
            for line in lines
            if line.line_kind == "option" and line.parent_product_id == main.product_id
        )
        selected, alternatives = _bundle_plan(connection, pools, main, options)
        main_projection = (
            selected.main.view,
            *(bundle.main.view for bundle in alternatives),
        )
        insert_comparisons(connection, main, main_projection)
        for index, option in enumerate(options):
            option_projection = (
                selected.options[index],
                *(bundle.options[index] for bundle in alternatives),
            )
            insert_comparisons(connection, option, option_projection)
            processed_options.add(option.id)
    for option in (
        line
        for line in lines
        if line.line_kind == "option" and line.id not in processed_options
    ):
        _seed_standalone_option(connection, pools, option)


def seed_comparisons_in_transaction(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> None:
    """Reseed the full persisted document instead of one stale line."""
    lines = stored_document_lines(connection, line)
    seed_document_comparisons_in_transaction(
        connection,
        lines or (line,),
    )


def _bundle_plan(
    connection: sqlite3.Connection,
    pools: BundleOptionPools,
    main: EstimateLine,
    options: tuple[EstimateLine, ...],
) -> tuple[BundleCandidate, tuple[BundleCandidate, ...]]:
    context = _BundleMatchContext(main, options, pools)
    ranked = rank_main_candidates(connection, main, options)
    selected_main = next(
        (
            candidate
            for candidate in ranked
            if candidate.view.product_id == main.product_id
            and candidate.view.company == main.company_snapshot
        ),
        _selected_main_candidate(main),
    )
    selected = BundleCandidate(
        selected_main,
        tuple(_selected_view(option) for option in options),
        _bundle_total(
            main,
            tuple(_selected_view(option) for option in options),
            options,
        ),
    )
    bundle_items: list[BundleCandidate] = []
    for candidate in ranked:
        if (
            candidate.view.product_id == selected.main.view.product_id
            and candidate.view.company == selected.main.view.company
        ):
            continue
        bundle = _candidate_bundle(
            context,
            candidate,
        )
        if bundle is not None:
            bundle_items.append(bundle)
    alternatives = _choose_aligned_bundles(
        connection,
        context,
        selected,
        tuple(bundle_items),
    )
    return selected, alternatives


def _choose_aligned_bundles(
    connection: sqlite3.Connection,
    context: _BundleMatchContext,
    selected: BundleCandidate,
    bundles: tuple[BundleCandidate, ...],
) -> tuple[BundleCandidate, ...]:
    ranked = rank_bundle_alternatives(
        bundles,
        selected,
        distinct_product_ids=requires_distinct_product_ids(
            connection,
            context.main,
        ),
    )
    distinct_options = tuple(
        requires_distinct_product_ids(connection, option) for option in context.options
    )
    used_ids: list[set[str]] = [
        {selected.options[index].product_id} if distinct else set()
        for index, distinct in enumerate(distinct_options)
    ]
    chosen: list[BundleCandidate] = []
    for bundle in ranked:
        adjusted = bundle
        if any(distinct_options):
            rematched = _candidate_bundle(
                context,
                bundle.main,
                tuple(used_ids),
            )
            if (
                rematched is None
                or rematched.total_price_won < selected.total_price_won
            ):
                continue
            adjusted = rematched
        if any(
            distinct and adjusted.options[index].product_id in used_ids[index]
            for index, distinct in enumerate(distinct_options)
        ):
            continue
        chosen.append(adjusted)
        for index, distinct in enumerate(distinct_options):
            if distinct:
                used_ids[index].add(adjusted.options[index].product_id)
        if len(chosen) == ALTERNATIVE_COUNT:
            break
    return tuple(chosen)


def _candidate_bundle(
    context: _BundleMatchContext,
    candidate: MainCandidate,
    used_ids: tuple[set[str], ...] | None = None,
) -> BundleCandidate | None:
    cache_key = context.pools.cache_key(candidate)
    if used_ids is None and cache_key in context.option_cache:
        cached = context.option_cache[cache_key]
        if cached is None:
            return None
        return BundleCandidate(
            candidate,
            cached,
            _bundle_total(
                context.main,
                cached,
                context.options,
                main_view=candidate.view,
            ),
        )
    group_candidates = context.pools.group_candidates(candidate)
    company_candidates = context.pools.company_candidates(candidate)
    matched: list[ComparisonView] = []
    for option in context.options:
        used_product_ids: set[str] = (
            set() if used_ids is None else used_ids[len(matched)]
        )
        view = match_bundle_option(
            option,
            candidate,
            used_product_ids,
            group_candidates,
        )
        if view is None:
            view = match_bundle_option(
                option,
                candidate,
                used_product_ids,
                company_candidates,
            )
        if view is None:
            if used_ids is None:
                context.option_cache[cache_key] = None
            return None
        matched.append(view)
    matched_options = tuple(matched)
    if used_ids is None:
        context.option_cache[cache_key] = matched_options
    return BundleCandidate(
        candidate,
        matched_options,
        _bundle_total(
            context.main,
            matched_options,
            context.options,
            main_view=candidate.view,
        ),
    )


def _bundle_total(
    main: EstimateLine,
    option_views: tuple[ComparisonView, ...],
    options: tuple[EstimateLine, ...],
    *,
    main_view: ComparisonView | None = None,
) -> Decimal:
    main_price = (
        main.unit_price_won_snapshot if main_view is None else main_view.price_won
    )
    return Decimal(main_price) * main.quantity + sum(
        (
            Decimal(view.price_won) * option.quantity
            for view, option in zip(option_views, options, strict=True)
        ),
        start=Decimal(0),
    )


def _selected_main_candidate(line: EstimateLine) -> MainCandidate:
    return MainCandidate(
        _selected_view(line),
        2_147_483_647,
        (0, 0, 0, 0, 0, 0, 0, line.product_id),
    )


def _selected_view(line: EstimateLine) -> ComparisonView:
    return ComparisonView(
        "",
        line.product_id,
        line.relation_id,
        line.company_snapshot,
        line.spec_snapshot,
        line.unit_price_won_snapshot,
    )


def _seed_standalone_option(
    connection: sqlite3.Connection,
    pools: BundleOptionPools,
    option: EstimateLine,
) -> None:
    parent = parent_line(connection, option)
    if parent is None:
        insert_comparisons(connection, option, (_selected_view(option),))
        return
    selected, alternatives = _bundle_plan(connection, pools, parent, (option,))
    insert_comparisons(
        connection,
        option,
        (
            selected.options[0],
            *(bundle.options[0] for bundle in alternatives),
        ),
    )
