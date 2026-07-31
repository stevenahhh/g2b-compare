"""Text normalization and option-label parsing for estimate comparisons."""

from __future__ import annotations

import html
import re

from g2b_compare.db.sql import SqlValue, as_text

from .estimate_models import ALTERNATIVE_COUNT


def parse_option_label(raw_label: str) -> tuple[str, str]:
    """Split one provider option label into item and specification text."""
    text = re.sub(r"^\[[^]]+\]\s*\[\d{8}\]\s*", "", raw_label).strip()
    text = re.sub(r"\s*:\s*[\d,]+\s*$", "", text)
    item_name, separator, spec = text.partition(",")
    if not separator:
        return text, text
    return item_name.strip(), spec.strip()


def text_or(value: SqlValue, fallback: str) -> str:
    """Return fallback text for an empty SQLite value."""
    return fallback if value is None or value == "" else as_text(value)


def normalize(value: str) -> str:
    """Normalize comparison text for deterministic matching."""
    decoded = html.unescape(value).casefold().replace("\N{MULTIPLICATION SIGN}", "x")
    return " ".join(re.sub(r"[^0-9a-z가-힣.]+", " ", decoded).split())


def number_key(value: str) -> str:
    """Canonicalize a numeric string without trailing zeroes."""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def cable_signature(item_name: str, spec: str) -> tuple[str, str] | None:
    """Return the cable type and length signature when applicable."""
    if "케이블" not in item_name:
        return None
    parts = tuple(re.sub(r"\s+", "", part).casefold() for part in spec.split(","))
    if len(parts) >= ALTERNATIVE_COUNT:
        return (parts[-2], parts[-1])
    return (parts[0] if parts else "", "")
