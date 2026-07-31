"""Match option candidates to selected option snapshots."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import TYPE_CHECKING

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


def option_alternatives(  # noqa: C901, PLR0912
    connection: sqlite3.Connection,
    line: EstimateLine,
    ranked_mains: tuple[_MainCandidate, ...],
    chosen_mains: tuple[_MainCandidate, ...],
) -> tuple[ComparisonView, ...]:
    """Choose deterministic compatible alternatives for one option line."""
    reserved_companies = {item.view.company for item in chosen_mains}
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    alternatives: list[ComparisonView] = []
    companies = {line.company_snapshot}
    used_product_ids: set[str] = {line.product_id} if requires_distinct_ids else set()
    for item in _same_option_relation_alternatives(connection, line):
        if item.company in companies or (
            requires_distinct_ids and item.product_id in used_product_ids
        ):
            continue
        alternatives.append(item)
        companies.add(item.company)
        if requires_distinct_ids:
            used_product_ids.add(item.product_id)
    if len(alternatives) == ALTERNATIVE_COUNT:
        return tuple(alternatives)
    for allow_expensive in (False, True):
        for preferred in chosen_mains or ranked_mains:
            candidate = _best_option_for_main(
                connection,
                line,
                preferred,
                used_product_ids,
                fallback=False,
                allow_expensive=allow_expensive,
            )
            if candidate is None:
                for fallback in ranked_mains:
                    if (
                        fallback.view.company in reserved_companies
                        or fallback.view.company in companies
                    ):
                        continue
                    candidate = _best_option_for_main(
                        connection,
                        line,
                        fallback,
                        used_product_ids,
                        fallback=True,
                        allow_expensive=allow_expensive,
                    )
                    if candidate is not None:
                        break
            if candidate is None or candidate.company in companies:
                continue
            alternatives.append(candidate)
            companies.add(candidate.company)
            if requires_distinct_ids:
                used_product_ids.add(candidate.product_id)
            if len(alternatives) == ALTERNATIVE_COUNT:
                break
        if len(alternatives) == ALTERNATIVE_COUNT:
            break
    return tuple(alternatives)


def _best_option_for_main(  # noqa: PLR0913
    connection: sqlite3.Connection,
    line: EstimateLine,
    main: _MainCandidate,
    used_product_ids: set[str],
    *,
    fallback: bool,
    allow_expensive: bool = False,
) -> ComparisonView | None:
    candidates = _group_option_candidates(connection, main.view.product_id)
    if not candidates:
        candidates = _company_option_candidates(connection, main.view.company)
    kind = _line_component(line)
    if kind is None:
        return None
    requirements = _option_requirements(kind, line.spec_snapshot)
    compatible: list[tuple[tuple[int, int, int, int, str], ComparisonView]] = []
    for candidate in candidates:
        if _canonical_component(candidate.item_name) != kind:
            continue
        if not _option_matches(line, candidate, kind, requirements):
            continue
        price = candidate.view.price_won
        if price < line.unit_price_won_snapshot:
            continue
        if not allow_expensive and not _within_price_limit(
            line.unit_price_won_snapshot, price, 110
        ):
            continue
        if candidate.view.product_id in used_product_ids:
            continue
        identity_penalty = int(
            candidate.view.product_id == line.product_id
            if fallback
            else candidate.view.product_id != line.product_id
        )
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
        key = (
            0,
            identity_penalty,
            similarity_penalty,
            price - line.unit_price_won_snapshot,
            candidate.view.product_id,
        )
        compatible.append((key, candidate.view))
    return min(compatible, default=((), None), key=lambda item: item[0])[1]


def _option_matches(
    line: EstimateLine,
    candidate: _OptionCandidate,
    kind: str,
    requirements: frozenset[str],
) -> bool:
    if kind == "cable":
        return candidate.view.product_id == line.product_id
    candidate_requirements = _option_requirements(kind, candidate.match_text)
    return not requirements or requirements <= candidate_requirements
