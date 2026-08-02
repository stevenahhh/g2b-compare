"""Match option candidates to selected option snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, TypeGuard

from .estimate_features import (
    canonical_component as _canonical_component,
)
from .estimate_features import (
    line_component as _line_component,
)
from .estimate_features import (
    option_requirements as _option_requirements,
)
from .estimate_models import (
    ALTERNATIVE_COUNT,
    ComparisonView,
)
from .estimate_models import (
    MainCandidate as _MainCandidate,
)
from .estimate_models import (
    OptionCandidate as _OptionCandidate,
)
from .estimate_option_lookup import (
    company_option_candidates as _company_option_candidates,
)
from .estimate_option_lookup import (
    group_option_candidates as _group_option_candidates,
)
from .estimate_option_lookup import (
    higher_same_option_relation_alternatives as _higher_same_option_relations,
)
from .estimate_option_lookup import (
    same_option_relation_alternatives as _same_option_relation_alternatives,
)
from .estimate_policy import (
    requires_distinct_product_ids as _requires_distinct_product_ids,
)
from .estimate_policy import (
    within_price_limit as _within_price_limit,
)
from .estimate_text import normalize as _normalize

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine

    from .estimate_option_pool import BundleOptionPools


@dataclass(frozen=True, slots=True)
class _OptionMatchContext:
    connection: sqlite3.Connection
    line: EstimateLine
    used_product_ids: set[str]
    pools: BundleOptionPools | None


@dataclass(frozen=True, slots=True)
class _SlotMatchContext:
    option: _OptionMatchContext
    fallback_mains: tuple[_MainCandidate, ...]
    exact_relations: tuple[ComparisonView, ...]
    companies: set[str]
    reserved: set[str]
    requires_distinct_ids: bool


@dataclass(frozen=True, slots=True)
class _CandidateMatchContext:
    option: _OptionMatchContext
    kind: str
    requirements: frozenset[str]
    fallback: bool
    allow_expensive: bool
    ordered_switch: bool


def option_alternatives(  # noqa: C901
    connection: sqlite3.Connection,
    line: EstimateLine,
    ranked_mains: tuple[_MainCandidate, ...],
    chosen_mains: tuple[_MainCandidate, ...],
    pools: BundleOptionPools | None = None,
) -> tuple[ComparisonView, ...]:
    """Choose deterministic compatible alternatives for one option line."""
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    alternatives: list[ComparisonView] = []
    companies = {line.company_snapshot}
    used_product_ids: set[str] = {line.product_id} if requires_distinct_ids else set()
    context = _OptionMatchContext(connection, line, used_product_ids, pools)

    def append(candidate: ComparisonView | None) -> None:
        if (
            candidate is None
            or candidate.company in companies
            or (requires_distinct_ids and candidate.product_id in used_product_ids)
        ):
            return
        alternatives.append(candidate)
        companies.add(candidate.company)
        if requires_distinct_ids:
            used_product_ids.add(candidate.product_id)

    for allow_expensive in (False, True):
        for preferred in chosen_mains:
            append(
                best_option_for_main(
                    context,
                    preferred,
                    fallback=False,
                    allow_expensive=allow_expensive,
                )
            )
            if len(alternatives) == ALTERNATIVE_COUNT:
                return tuple(alternatives)
    for candidate in _same_option_relation_alternatives(connection, line):
        append(candidate)
        if len(alternatives) == ALTERNATIVE_COUNT:
            return tuple(alternatives)
    for allow_expensive in (False, True):
        for fallback in ranked_mains:
            if fallback.view.company in companies:
                continue
            append(
                best_option_for_main(
                    context,
                    fallback,
                    fallback=True,
                    allow_expensive=allow_expensive,
                )
            )
            if len(alternatives) == ALTERNATIVE_COUNT:
                return tuple(alternatives)
    return tuple(alternatives)


def slot_option_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
    ranked_mains: tuple[_MainCandidate, ...],
    chosen_mains: tuple[_MainCandidate, ...],
    pools: BundleOptionPools,
) -> tuple[ComparisonView, ...]:
    """Fill each main slot before advancing to the next comparison column."""
    if _uses_priority_option_order(line):
        return _priority_ordered_alternatives(line, chosen_mains, pools)
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    used_ids: set[str] = {line.product_id} if requires_distinct_ids else set()
    context = _OptionMatchContext(connection, line, used_ids, pools)
    companies = {line.company_snapshot}
    reserved = {main.view.company for main in chosen_mains}
    alternatives: list[ComparisonView] = []
    exact_relations = (
        _higher_same_option_relations(connection, line)
        if _line_component(line) == "dvr" or "cms" in _normalize(line.spec_snapshot)
        else ()
    )
    fallback_mains = _unique_fallback_mains(ranked_mains, pools)
    slot_context = _SlotMatchContext(
        context,
        fallback_mains,
        exact_relations,
        companies,
        reserved,
        requires_distinct_ids,
    )
    for preferred in chosen_mains:
        selected = _choose_slot_option(slot_context, preferred)
        if selected is None:
            continue
        alternatives.append(selected)
        companies.add(selected.company)
        if requires_distinct_ids:
            used_ids.add(selected.product_id)
    return tuple(alternatives)


def _unique_fallback_mains(
    ranked_mains: tuple[_MainCandidate, ...],
    pools: BundleOptionPools,
) -> tuple[_MainCandidate, ...]:
    result: list[_MainCandidate] = []
    keys: set[tuple[str, str]] = set()
    for candidate in ranked_mains:
        cache_key = pools.cache_key(candidate)
        if cache_key in keys:
            continue
        keys.add(cache_key)
        result.append(candidate)
    return tuple(result)


def _option_available(
    candidate: ComparisonView | None,
    companies: set[str],
    used_product_ids: set[str],
    *,
    requires_distinct_ids: bool,
) -> TypeGuard[ComparisonView]:
    return (
        candidate is not None
        and candidate.company not in companies
        and not (requires_distinct_ids and candidate.product_id in used_product_ids)
    )


def _direct_slot_choices(
    context: _SlotMatchContext,
    preferred: _MainCandidate,
    blocked: set[str],
    *,
    allow_expensive: bool,
) -> list[ComparisonView]:
    candidate = best_option_for_main(
        context.option,
        preferred,
        fallback=False,
        allow_expensive=allow_expensive,
    )
    exact = next(
        (
            item
            for item in context.exact_relations
            if item.company not in context.companies
            and item.company not in blocked
            and item.price_won > context.option.line.unit_price_won_snapshot
        ),
        None,
    )
    return [
        item
        for item in (candidate, exact)
        if _option_available(
            item,
            context.companies,
            context.option.used_product_ids,
            requires_distinct_ids=context.requires_distinct_ids,
        )
    ]


def _fallback_slot_choice(
    context: _SlotMatchContext,
    blocked: set[str],
    *,
    allow_expensive: bool,
) -> ComparisonView | None:
    for fallback in context.fallback_mains:
        if (
            fallback.view.company in context.companies
            or fallback.view.company in blocked
        ):
            continue
        candidate = best_option_for_main(
            context.option,
            fallback,
            fallback=True,
            allow_expensive=allow_expensive,
        )
        if _option_available(
            candidate,
            context.companies,
            context.option.used_product_ids,
            requires_distinct_ids=context.requires_distinct_ids,
        ):
            return candidate
    return None


def _choose_slot_option(
    context: _SlotMatchContext,
    preferred: _MainCandidate,
) -> ComparisonView | None:
    blocked = context.reserved - {preferred.view.company}
    cms_line = "cms" in _normalize(context.option.line.spec_snapshot)
    for allow_expensive in (False, True):
        direct_choices = _direct_slot_choices(
            context,
            preferred,
            blocked,
            allow_expensive=allow_expensive,
        )
        if direct_choices and not cms_line:
            return _closest_option(context.option.line, direct_choices)
        fallback = _fallback_slot_choice(
            context,
            blocked,
            allow_expensive=allow_expensive,
        )
        if fallback is not None and not cms_line:
            return fallback
        if fallback is not None:
            direct_choices.append(fallback)
        if direct_choices:
            return _closest_option(context.option.line, direct_choices)
    return None


def _closest_option(
    line: EstimateLine,
    candidates: list[ComparisonView],
) -> ComparisonView:
    return min(
        candidates,
        key=lambda item: (
            item.price_won - line.unit_price_won_snapshot,
            item.product_id,
        ),
    )


def best_option_for_main(
    context: _OptionMatchContext,
    main: _MainCandidate,
    *,
    fallback: bool,
    allow_expensive: bool = False,
) -> ComparisonView | None:
    """Return the closest compatible option offered with one main product."""
    candidates = (
        (
            *_group_option_candidates(
                context.connection,
                main.view.product_id,
            ),
            *_company_option_candidates(
                context.connection,
                main.view.company,
            ),
        )
        if context.pools is None
        else context.pools.candidates(main)
    )
    kind = _line_component(context.line)
    if kind is None:
        return None
    requirements = _option_requirements(kind, context.line.spec_snapshot)
    ordered_switch = (
        kind == "switch" and "ports:24" in requirements and context.line.quantity > 1
    )
    match_context = _CandidateMatchContext(
        context,
        kind,
        requirements,
        fallback,
        allow_expensive,
        ordered_switch,
    )
    compatible: list[tuple[tuple[int, int, int, int, int, str], ComparisonView]] = []
    for candidate in candidates:
        key = _option_candidate_key(match_context, candidate)
        if key is not None:
            compatible.append((key, candidate.view))
    return min(compatible, default=((), None), key=lambda item: item[0])[1]


def _option_candidate_key(
    context: _CandidateMatchContext,
    candidate: _OptionCandidate,
) -> tuple[int, int, int, int, int, str] | None:
    line = context.option.line
    if not _option_candidate_eligible(context, candidate):
        return None
    price = candidate.view.price_won
    similarity_penalty = 0
    if context.kind == "hdd":
        similarity_penalty = -int(
            SequenceMatcher(
                None,
                _normalize(line.spec_snapshot),
                _normalize(candidate.match_text),
            ).ratio()
            * 1000
        )
    return (
        int(not context.fallback and candidate.view.product_id != line.product_id),
        similarity_penalty,
        candidate.source_priority if context.ordered_switch else 1,
        candidate.source_order if context.ordered_switch else 0,
        price - line.unit_price_won_snapshot,
        candidate.view.product_id,
    )


def _option_candidate_eligible(
    context: _CandidateMatchContext,
    candidate: _OptionCandidate,
) -> bool:
    line = context.option.line
    price = candidate.view.price_won
    same_selected_price = (
        candidate.view.product_id == line.product_id
        and price == line.unit_price_won_snapshot
    )
    return (
        _canonical_component(candidate.item_name) == context.kind
        and _option_matches(
            line,
            candidate,
            context.kind,
            context.requirements,
        )
        and price >= line.unit_price_won_snapshot
        and not (
            "cms" in _normalize(line.spec_snapshot)
            and price == line.unit_price_won_snapshot
        )
        and not (context.fallback and same_selected_price)
        and (
            context.allow_expensive
            or _within_price_limit(
                line.unit_price_won_snapshot,
                price,
                20 if context.ordered_switch else 110,
            )
        )
        and candidate.view.product_id not in context.option.used_product_ids
    )


def match_bundle_option(
    line: EstimateLine,
    main: _MainCandidate,
    used_product_ids: set[str],
    candidates: tuple[_OptionCandidate, ...],
) -> ComparisonView | None:
    """Match one option to the same company without repeated database reads."""
    kind = _line_component(line)
    if kind is None:
        return None
    requirements = _option_requirements(kind, line.spec_snapshot)
    compatible: list[tuple[tuple[int, int, int, str], ComparisonView]] = []
    for candidate in candidates:
        if candidate.view.company != main.view.company:
            continue
        if _canonical_component(candidate.item_name) != kind:
            continue
        if not _option_matches(line, candidate, kind, requirements):
            continue
        if candidate.view.product_id in used_product_ids:
            continue
        if candidate.view.price_won < line.unit_price_won_snapshot:
            continue
        similarity_penalty = 0
        if kind == "hdd":
            similarity_penalty = -int(
                SequenceMatcher(
                    None,
                    _normalize(line.spec_snapshot),
                    _normalize(candidate.match_text),
                ).ratio()
                * 1000
            )
        compatible.append(
            (
                (
                    int(candidate.view.product_id != line.product_id),
                    similarity_penalty,
                    abs(candidate.view.price_won - line.unit_price_won_snapshot),
                    candidate.view.product_id,
                ),
                candidate.view,
            )
        )
    return min(compatible, default=((), None), key=lambda item: item[0])[1]


def _option_matches(
    line: EstimateLine,
    candidate: _OptionCandidate,
    kind: str,
    requirements: frozenset[str],
) -> bool:
    if candidate.view.product_id == line.product_id:
        return True
    if kind == "cable":
        return False
    candidate_requirements = _option_requirements(kind, candidate.match_text)
    if kind == "switch":
        requirements = requirements - {"poe"}
        candidate_requirements = candidate_requirements - {"poe"}
    return not requirements or requirements <= candidate_requirements


def _uses_priority_option_order(line: EstimateLine) -> bool:
    normalized = _normalize(f"{line.item_name_snapshot} {line.spec_snapshot}")
    return any(
        marker in normalized
        for marker in (
            "금속상자",
            "전원공급장치",
            "모니터",
            "수신기",
            "송신기",
            "장비용랙",
            "서지",
        )
    )


def _priority_ordered_alternatives(
    line: EstimateLine,
    chosen_mains: tuple[_MainCandidate, ...],
    pools: BundleOptionPools,
) -> tuple[ComparisonView, ...]:
    kind = _line_component(line)
    if kind is None:
        return ()
    requirements = _option_requirements(kind, line.spec_snapshot)
    chosen: list[ComparisonView] = []
    if chosen_mains:
        preferred = chosen_mains[0]
        direct = match_bundle_option(
            line,
            preferred,
            set(),
            pools.group_candidates(preferred),
        )
        if direct is not None and direct.product_id != line.product_id:
            chosen.append(direct)
    eligible = _eligible_priority_options(
        line,
        pools,
        kind,
        requirements,
    )
    companies = {line.company_snapshot, *(view.company for view in chosen)}
    product_ids = {view.product_id for view in chosen}
    distinct_ids = {
        candidate.view.product_id
        for candidate in eligible
        if candidate.view.product_id != line.product_id
    }
    if len(distinct_ids) >= ALTERNATIVE_COUNT:
        eligible = [
            candidate
            for candidate in eligible
            if candidate.view.product_id != line.product_id
        ]
    eligible.sort(
        key=lambda candidate: (
            candidate.source_order,
            candidate.view.price_won - line.unit_price_won_snapshot,
            candidate.view.company.encode("utf-8"),
            candidate.view.product_id,
        )
    )
    while len(chosen) < ALTERNATIVE_COUNT:
        selected = _next_priority_option(
            eligible,
            companies,
            product_ids,
        )
        if selected is None:
            break
        chosen.append(selected.view)
        companies.add(selected.view.company)
        product_ids.add(selected.view.product_id)
    return tuple(chosen)


def _eligible_priority_options(
    line: EstimateLine,
    pools: BundleOptionPools,
    kind: str,
    requirements: frozenset[str],
) -> list[_OptionCandidate]:
    return [
        candidate
        for candidate in pools.all_candidates()
        if candidate.view.relation_id is None
        and _canonical_component(candidate.item_name) == kind
        and _option_matches(line, candidate, kind, requirements)
        and candidate.view.price_won >= line.unit_price_won_snapshot
    ]


def _next_priority_option(
    eligible: list[_OptionCandidate],
    companies: set[str],
    product_ids: set[str],
) -> _OptionCandidate | None:
    has_unused_product = any(
        item.view.product_id not in product_ids and item.view.company not in companies
        for item in eligible
    )
    return next(
        (
            candidate
            for candidate in eligible
            if candidate.view.company not in companies
            and (candidate.view.product_id not in product_ids or not has_unused_product)
        ),
        None,
    )
