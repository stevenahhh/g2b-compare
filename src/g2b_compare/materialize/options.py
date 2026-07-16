"""Build deterministic ranking option text from raw product evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.normalize.text import normalize_text

if TYPE_CHECKING:
    from .attributes import ProductAttribute


@dataclass(frozen=True, slots=True)
class FallbackText:
    """Ordered unstructured fields appended after available attributes."""

    spec_name: str
    detail: str
    characteristic: str


@dataclass(frozen=True, slots=True)
class OptionText:
    """Byte-stable ranking text and its ordered normalized segments."""

    segments: tuple[str, ...]
    text: str
    utf8_sha256: str


def build_option_text(
    attributes: tuple[ProductAttribute, ...],
    fallbacks: FallbackText,
) -> OptionText:
    """Concatenate nonempty unique segments with the fixed ASCII delimiter."""
    candidates: list[str] = []
    for attribute in sorted(
        attributes,
        key=lambda item: (item.attribute_key, item.ordinal, item.attribute_source_key),
    ):
        name = normalize_text(attribute.raw_name).derived
        value = normalize_text(attribute.raw_value).derived
        if name and value:
            candidates.append(f"attr:{name}={value}")
    candidates.extend(
        _fallback_segments(
            (
                ("spec", fallbacks.spec_name),
                ("detail", fallbacks.detail),
                ("characteristic", fallbacks.characteristic),
            )
        )
    )
    unique = tuple(dict.fromkeys(candidates))
    text = " | ".join(unique)
    return OptionText(unique, text, hashlib.sha256(text.encode("utf-8")).hexdigest())


def _fallback_segments(values: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    segments: list[str] = []
    for prefix, raw in values:
        normalized = normalize_text(raw).derived
        if normalized:
            segments.append(f"{prefix}:{normalized}")
    return tuple(segments)
