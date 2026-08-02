"""Select document comparison columns from ranked main candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .estimate_features import (
    canonical_component,
    line_component,
    option_requirements,
)
from .estimate_models import ALTERNATIVE_COUNT, MainCandidate
from .estimate_policy import within_price_limit

if TYPE_CHECKING:
    from collections.abc import Iterable

    from g2b_compare.services import EstimateLine

    from .estimate_option_pool import BundleOptionPools


STANDARD_PRIORITY_CUTOFF: Final = 1_000_000


def choose_document_main_alternatives(
    line: EstimateLine,
    options: tuple[EstimateLine, ...],
    ranked: tuple[MainCandidate, ...],
    pools: BundleOptionPools,
) -> tuple[MainCandidate, ...]:
    """Choose stable main slots with fallback-option coverage."""
    eligible = tuple(
        candidate
        for candidate in ranked
        if candidate.view.company != line.company_snapshot
        and candidate.view.price_won >= line.unit_price_won_snapshot
        and within_price_limit(
            line.unit_price_won_snapshot,
            candidate.view.price_won,
            110,
        )
    )
    standard = _distinct_companies(
        candidate
        for candidate in eligible
        if candidate.key[0] < STANDARD_PRIORITY_CUTOFF
    )
    if len(standard) >= ALTERNATIVE_COUNT:
        return tuple(
            sorted(
                standard[:ALTERNATIVE_COUNT],
                key=lambda candidate: (
                    candidate.source_row,
                    candidate.view.product_id,
                ),
            )
        )
    fallback = _distinct_companies(eligible)
    if not fallback:
        return ()
    first = min(
        fallback,
        key=lambda candidate: (
            candidate.view.price_won - line.unit_price_won_snapshot,
            candidate.key,
        ),
    )
    remaining = tuple(
        candidate
        for candidate in fallback
        if candidate.view.company != first.view.company
    )
    if not remaining:
        return (first,)
    coverage: dict[tuple[str, str], int] = {}

    def coverage_key(
        candidate: MainCandidate,
    ) -> tuple[int, int, tuple[int, int, int, int, int, int, int, str]]:
        cache_key = pools.cache_key(candidate)
        count = coverage.get(cache_key)
        if count is None:
            option_candidates = pools.group_candidates(candidate)
            count = sum(
                any(
                    canonical_component(option_candidate.item_name)
                    == line_component(option)
                    and option_candidate.view.price_won
                    >= option.unit_price_won_snapshot
                    and _coarse_requirements(option)
                    <= _coarse_candidate_requirements(
                        option,
                        option_candidate.match_text,
                    )
                    for option_candidate in option_candidates
                )
                for option in options
            )
            coverage[cache_key] = count
        return (
            -count,
            candidate.view.price_won - line.unit_price_won_snapshot,
            candidate.key,
        )

    return first, min(remaining, key=coverage_key)


def _distinct_companies(
    candidates: Iterable[MainCandidate],
) -> tuple[MainCandidate, ...]:
    result: list[MainCandidate] = []
    companies: set[str] = set()
    for candidate in candidates:
        if candidate.view.company in companies:
            continue
        companies.add(candidate.view.company)
        result.append(candidate)
    return tuple(result)


def _coarse_requirements(line: EstimateLine) -> frozenset[str]:
    kind = line_component(line)
    if kind is None:
        return frozenset()
    return _without_structural_requirements(
        option_requirements(kind, line.spec_snapshot)
    )


def _coarse_candidate_requirements(
    line: EstimateLine,
    text: str,
) -> frozenset[str]:
    kind = line_component(line)
    if kind is None:
        return frozenset()
    return _without_structural_requirements(option_requirements(kind, text))


def _without_structural_requirements(
    requirements: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        requirement
        for requirement in requirements
        if not requirement.startswith(("dimension:", "inch:", "surge:", "role:"))
    )
