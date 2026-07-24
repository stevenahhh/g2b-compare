"""Context-aware maximum-weight matching for parsed specifications."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Final

from .formula import range_similarity, value_similarity
from .matching_context import (
    ContextSpec,
    context_is_eligible,
    context_similarity,
    extract_context_specs,
)

__all__ = (
    "ContextSpec",
    "context_is_eligible",
    "context_similarity",
    "extract_context_specs",
)
UNKNOWN_ATTRIBUTES: Final = frozenset(("", "unknown"))


@dataclass(frozen=True, slots=True)
class MatchedPair:
    """One deterministic anchor-to-candidate structured edge."""

    anchor: ContextSpec
    candidate: ContextSpec
    weight: Decimal


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Maximum-weight matching normalized by all anchor specs."""

    anchor_count: int
    matched_anchor_count: int
    weight_sum: Decimal
    similarity: Decimal | None
    pairs: tuple[MatchedPair, ...]


@dataclass(frozen=True, slots=True)
class _Choice:
    weight: Decimal
    pairs: tuple[tuple[int, int, Decimal], ...]


def match_specs(anchor_text: str, candidate_text: str) -> MatchResult:
    """Parse two option texts and return their deterministic best matching."""
    anchor = extract_context_specs(anchor_text)
    candidate = extract_context_specs(candidate_text)
    if not anchor:
        return MatchResult(0, 0, Decimal(0), None, ())
    choice = _maximum_matching(anchor, candidate)
    pairs = tuple(
        MatchedPair(anchor[left], candidate[right], weight)
        for left, right, weight in choice.pairs
    )
    return MatchResult(
        len(anchor),
        len(pairs),
        choice.weight,
        choice.weight / Decimal(len(anchor)),
        pairs,
    )


def _maximum_matching(
    anchor: tuple[ContextSpec, ...], candidate: tuple[ContextSpec, ...]
) -> _Choice:
    dimensions_anchor = _dimension_counts(anchor)
    dimensions_candidate = _dimension_counts(candidate)
    direct = _unique_known_choice(
        anchor,
        candidate,
        dimensions_anchor,
        dimensions_candidate,
    )
    if direct is not None:
        return direct

    @cache
    def visit(anchor_index: int, used: int) -> _Choice:
        if anchor_index == len(anchor):
            return _Choice(Decimal(0), ())
        best = visit(anchor_index + 1, used)
        for candidate_index, candidate_spec in enumerate(candidate):
            if used & (1 << candidate_index):
                continue
            weight = _edge_weight(
                anchor[anchor_index],
                candidate_spec,
                dimensions_anchor,
                dimensions_candidate,
            )
            if weight is None:
                continue
            tail = visit(anchor_index + 1, used | (1 << candidate_index))
            current = _Choice(
                weight + tail.weight,
                ((anchor_index, candidate_index, weight), *tail.pairs),
            )
            if _better(current, best, anchor, candidate):
                best = current
        return best

    return visit(0, 0)


def _unique_known_choice(
    anchor: tuple[ContextSpec, ...],
    candidate: tuple[ContextSpec, ...],
    anchor_counts: dict[str, int],
    candidate_counts: dict[str, int],
) -> _Choice | None:
    anchor_keys = tuple(item.semantic.attribute_key for item in anchor)
    candidate_keys = tuple(item.semantic.attribute_key for item in candidate)
    if (
        any(key in UNKNOWN_ATTRIBUTES for key in (*anchor_keys, *candidate_keys))
        or len(set(anchor_keys)) != len(anchor_keys)
        or len(set(candidate_keys)) != len(candidate_keys)
    ):
        return None
    candidate_by_key = {key: index for index, key in enumerate(candidate_keys)}
    pairs: list[tuple[int, int, Decimal]] = []
    for anchor_index, key in enumerate(anchor_keys):
        candidate_index = candidate_by_key.get(key)
        if candidate_index is None:
            continue
        weight = _edge_weight(
            anchor[anchor_index],
            candidate[candidate_index],
            anchor_counts,
            candidate_counts,
        )
        if weight is not None:
            pairs.append((anchor_index, candidate_index, weight))
    return _Choice(sum((pair[2] for pair in pairs), Decimal(0)), tuple(pairs))


def _dimension_counts(specs: tuple[ContextSpec, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in specs:
        dimension = spec.semantic.dimension
        counts[dimension] = counts.get(dimension, 0) + 1
    return counts


def _edge_weight(
    anchor: ContextSpec,
    candidate: ContextSpec,
    anchor_counts: dict[str, int],
    candidate_counts: dict[str, int],
) -> Decimal | None:
    left = anchor.semantic
    right = candidate.semantic
    if left.dimension != right.dimension or left.relation != right.relation:
        return None
    known_equal = (
        left.attribute_key == right.attribute_key
        and left.attribute_key not in UNKNOWN_ATTRIBUTES
    )
    unknown_context = context_is_eligible(
        context_similarity(anchor.context, candidate.context)
    ) and (
        left.attribute_key in UNKNOWN_ATTRIBUTES
        or right.attribute_key in UNKNOWN_ATTRIBUTES
    )
    unique_empty = (
        not anchor.context
        and not candidate.context
        and anchor_counts[left.dimension] == 1
        and candidate_counts[right.dimension] == 1
    )
    if not (known_equal or unknown_context or unique_empty):
        return None
    if left.lower is not None and left.upper is not None:
        if right.lower is None or right.upper is None:
            return None
        return range_similarity((left.lower, left.upper), (right.lower, right.upper))
    if left.value is None or right.value is None:
        return None
    return value_similarity(left.value, right.value)


def _better(
    current: _Choice,
    previous: _Choice,
    anchor: tuple[ContextSpec, ...],
    candidate: tuple[ContextSpec, ...],
) -> bool:
    if current.weight != previous.weight:
        return current.weight > previous.weight
    return _tie_key(current, anchor, candidate) < _tie_key(previous, anchor, candidate)


def _tie_key(
    choice: _Choice,
    anchor: tuple[ContextSpec, ...],
    candidate: tuple[ContextSpec, ...],
) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (
            anchor[left].semantic.source_span.start_byte,
            candidate[right].semantic.source_span.start_byte,
            left,
            right,
        )
        for left, right, _weight in choice.pairs
    )
