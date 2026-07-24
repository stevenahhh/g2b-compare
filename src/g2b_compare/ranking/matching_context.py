"""Parsed specification context extraction and similarity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
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

CONTEXT_THRESHOLD: Final = Decimal("0.75")
MATCHING_CACHE_MAXSIZE: Final = 150_000
_ATTRIBUTE_EQUALS: Final = re.compile(r"(?<![<>])=(?!=)")


@dataclass(frozen=True, slots=True)
class ContextSpec:
    """One parsed semantic with its regex-v1 local context."""

    semantic: SpecSemantic
    context: str
    ordinal: int


@lru_cache(maxsize=MATCHING_CACHE_MAXSIZE)
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


@lru_cache(maxsize=MATCHING_CACHE_MAXSIZE)
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


def matching_cache_maxsizes() -> tuple[int, int]:
    """Return the extraction and character-gram cache bounds."""
    extract = extract_context_specs.cache_info().maxsize or 0
    grams = _char_wb_grams.cache_info().maxsize or 0
    return extract, grams


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
