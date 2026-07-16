"""Context-aware maximum-weight matching for parsed specifications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from math import sqrt
from typing import Final

from g2b_compare.normalize.numbers import NumberParseError
from g2b_compare.normalize.spec_types import (
    RangeParseError,
    RelationParseError,
    SpecSemantic,
    UnitDimensionError,
)
from g2b_compare.normalize.specs import parse_specs
from g2b_compare.normalize.units import UnitAliasError

from .formula import range_similarity, value_similarity

CONTEXT_THRESHOLD: Final = Decimal("0.75")
UNKNOWN_ATTRIBUTES: Final = frozenset(("", "unknown"))
_ATTRIBUTE_EQUALS: Final = re.compile(r"(?<![<>])=(?!=)")


@dataclass(frozen=True, slots=True)
class ContextSpec:
    """One parsed semantic with its regex-v1 local context."""

    semantic: SpecSemantic
    context: str
    ordinal: int


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


def extract_context_specs(text: str) -> tuple[ContextSpec, ...]:
    """Attach three-token left and right context to every parsed semantic."""
    try:
        parsed = parse_specs(_ATTRIBUTE_EQUALS.sub(" ", text))
    except (
        NumberParseError,
        RangeParseError,
        RelationParseError,
        UnitDimensionError,
        UnitAliasError,
    ):
        return ()
    token_positions = _span_token_positions(parsed.normalized.tokens, parsed.semantics)
    return tuple(
        ContextSpec(
            semantic,
            _local_context(parsed.normalized.tokens, token_positions[index]),
            index,
        )
        for index, semantic in enumerate(parsed.semantics)
    )


def context_similarity(left: str, right: str) -> Decimal:
    """Calculate binary char_wb 3-5 gram cosine."""
    if not left or not right:
        return Decimal(0)
    left_grams = _char_wb_grams(left)
    right_grams = _char_wb_grams(right)
    if not left_grams or not right_grams:
        return Decimal(0)
    score = len(left_grams & right_grams) / sqrt(len(left_grams) * len(right_grams))
    return Decimal(str(score))


def context_is_eligible(similarity: Decimal) -> bool:
    """Apply the inclusive v1 unknown-attribute context boundary."""
    return similarity >= CONTEXT_THRESHOLD


def _char_wb_grams(text: str) -> frozenset[str]:
    grams: set[str] = set()
    for word in text.split():
        padded = f" {word} "
        for size in range(3, 6):
            if size >= len(padded):
                grams.add(padded)
                break
            grams.update(
                padded[start : start + size] for start in range(len(padded) - size + 1)
            )
    return frozenset(grams)


def _span_token_positions(
    tokens: tuple[str, ...], semantics: tuple[SpecSemantic, ...]
) -> tuple[int, ...]:
    positions: list[int] = []
    cursor = 0
    previous_span: tuple[int, int] | None = None
    previous_position = 0
    for semantic in semantics:
        span_key = (semantic.source_span.start_byte, semantic.source_span.end_byte)
        if span_key == previous_span:
            positions.append(previous_position)
            continue
        position = next(
            (
                index
                for index in range(cursor, len(tokens))
                if tokens[index] == semantic.source_span.normalized
            ),
            cursor,
        )
        positions.append(position)
        cursor = position + 1
        previous_span = span_key
        previous_position = position
    return tuple(positions)


def _local_context(tokens: tuple[str, ...], quantity_index: int) -> str:
    left = tokens[max(0, quantity_index - 3) : quantity_index]
    right = tokens[quantity_index + 1 : quantity_index + 4]
    return " ".join((*left, *right))


def _maximum_matching(
    anchor: tuple[ContextSpec, ...], candidate: tuple[ContextSpec, ...]
) -> _Choice:
    dimensions_anchor = _dimension_counts(anchor)
    dimensions_candidate = _dimension_counts(candidate)

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
