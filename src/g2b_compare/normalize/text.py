"""Derive a source-preserving NFKC and protected-token text view."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .tokens import PROTECTED_PATTERN, UNSUPPORTED_COMPOUND_PATTERN, tokenize


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    """Locate one protected normalized token in the original UTF-8 bytes."""

    start_byte: int
    end_byte: int
    raw: str
    normalized: str


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Keep the raw input beside its deterministic derived representation."""

    raw: str
    derived: str
    tokens: tuple[str, ...]
    protected: tuple[ProtectedSpan, ...]


def _nfkc_with_source_boundaries(
    raw: str,
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    normalized_offsets: list[int] = [0]
    byte_offsets: list[int] = [0]
    prefix = ""
    byte_offset = 0
    for character in raw:
        prefix += character
        byte_offset += len(character.encode("utf-8"))
        normalized_offsets.append(len(unicodedata.normalize("NFKC", prefix)))
        byte_offsets.append(byte_offset)
    return (
        unicodedata.normalize("NFKC", raw),
        tuple(normalized_offsets),
        tuple(byte_offsets),
    )


def _source_span(
    normalized_offsets: tuple[int, ...],
    byte_offsets: tuple[int, ...],
    start: int,
    end: int,
) -> tuple[int, int]:
    start_index = bisect_right(normalized_offsets, start) - 1
    end_index = bisect_left(normalized_offsets, end)
    return byte_offsets[start_index], byte_offsets[end_index]


def normalize_text(raw: str) -> NormalizedText:
    """Normalize a derived view while preserving quantity case and source bytes."""
    nfkc, normalized_offsets, byte_offsets = _nfkc_with_source_boundaries(raw)
    pieces: list[str] = []
    protected: list[ProtectedSpan] = []
    cursor = 0
    raw_bytes = raw.encode("utf-8")
    unsupported = tuple(
        match.span() for match in UNSUPPORTED_COMPOUND_PATTERN.finditer(nfkc)
    )
    for match in PROTECTED_PATTERN.finditer(nfkc):
        overlaps_unsupported = any(
            match.start() < end and match.end() > start for start, end in unsupported
        )
        if overlaps_unsupported:
            continue
        pieces.append(nfkc[cursor : match.start()].casefold())
        pieces.append(match.group(0))
        start_byte, end_byte = _source_span(
            normalized_offsets,
            byte_offsets,
            match.start(),
            match.end(),
        )
        protected.append(
            ProtectedSpan(
                start_byte,
                end_byte,
                raw_bytes[start_byte:end_byte].decode("utf-8"),
                match.group(0),
            ),
        )
        cursor = match.end()
    pieces.append(nfkc[cursor:].casefold())
    derived = re.sub(r"\s+", " ", "".join(pieces)).strip()
    return NormalizedText(raw, derived, tokenize(derived), tuple(protected))
