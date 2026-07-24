"""Derive a source-preserving NFKC and protected-token text view."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from .tokens import PROTECTED_PATTERN, UNSUPPORTED_COMPOUND_PATTERN, tokenize
from .units import ALIASES, resolve_unit

_MP_PATTERN: Final = re.compile(
    r"(?<![0-9a-z])(?P<value>\d+(?:\.\d+)?)\s*(?:mp|메가\s*픽셀)(?![0-9a-z])",
    re.IGNORECASE,
)
_PIXEL_PATTERN: Final = re.compile(
    r"(?<![0-9])(?P<value>[\d,]+(?:\.\d+)?)\s*만\s*화\s*소(?![0-9])",
)
_ZOOM_PATTERN: Final = re.compile(
    r"(?:"
    r"(?:optical|광학)\s*x?\s*(?P<optical>\d+(?:\.\d+)?)(?:\s*배\s*)?줌?"
    r"|(?P<plain>\d+(?:\.\d+)?)\s*배\s*줌"
    r")",
    re.IGNORECASE,
)
_SEARCH_UNIT_PATTERN: Final = "|".join(
    re.escape(alias.casefold())
    for alias in sorted(set(ALIASES), key=lambda alias: (-len(alias), alias))
)
_QUANTITY_PATTERN: Final = re.compile(
    rf"(?<![0-9a-z])(?P<value>\d{{1,6}}(?:,\d{{3}})*(?:\.\d+)?)\s*(?P<unit>{_SEARCH_UNIT_PATTERN})(?![0-9a-z])",
    re.IGNORECASE,
)
_SEARCH_UNITS: Final = {alias.casefold(): resolve_unit(alias) for alias in ALIASES}


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalize_search_text(raw: str) -> str:
    """Add searchable aliases for equivalent camera specification notation."""
    normalized = unicodedata.normalize("NFKC", raw).casefold()
    aliases: list[str] = []
    for match in _QUANTITY_PATTERN.finditer(normalized):
        value = Decimal(match.group("value").replace(",", ""))
        unit = _SEARCH_UNITS[match.group("unit").casefold()]
        aliases.append(f"{_decimal_text(value * unit.factor)}{unit.canonical}")
    for match in _MP_PATTERN.finditer(normalized):
        megapixels = Decimal(match.group("value"))
        aliases.append(f"{_decimal_text(megapixels * 100)}만화소")
    for match in _PIXEL_PATTERN.finditer(normalized):
        pixels_in_manhwa = Decimal(match.group("value").replace(",", ""))
        aliases.extend(
            (
                f"{_decimal_text(pixels_in_manhwa / 100)}mp",
                f"{_decimal_text(pixels_in_manhwa * 10000)}pixel",
            )
        )
    for match in _ZOOM_PATTERN.finditer(normalized):
        zoom = match.group("optical") or match.group("plain")
        if zoom is not None:
            aliases.extend(
                (f"{zoom}times", f"{zoom}배줌", f"optical x{zoom}", f"광학{zoom}배줌")
            )
    return " ".join((normalized, *aliases)).strip()


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
