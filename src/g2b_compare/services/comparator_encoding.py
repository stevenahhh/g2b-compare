"""Normalize primitive values used by persisted comparator payloads."""

from __future__ import annotations

import unicodedata
from decimal import Decimal
from typing import Final

from g2b_compare.ranking.cache import CacheContractError
from g2b_compare.ranking.formula import quantize_score

ROLE_SEQUENCE_INVALID: Final = "cache-role-sequence-invalid"


def fixed_decimal(value: Decimal | None) -> str | None:
    """Format one score with the canonical Ranking-v1 precision."""
    return None if value is None else format(quantize_score(value), "f")


def normalize_payload_text(value: str) -> str:
    """Normalize payload text to NFKC and LF line endings."""
    return unicodedata.normalize("NFKC", value.replace("\r\n", "\n"))


def parse_decimal(value: str | None) -> Decimal | None:
    """Parse an optional fixed-decimal payload value."""
    return None if value is None else Decimal(value)


def sequence_number(value: str) -> int:
    """Parse a persisted option-role sequence or reject the payload."""
    try:
        return int(value)
    except ValueError as error:
        raise CacheContractError(ROLE_SEQUENCE_INVALID) from error
