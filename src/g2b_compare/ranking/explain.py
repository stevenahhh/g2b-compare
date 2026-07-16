"""Immutable score evidence returned with each comparator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Activity:
    """Anchor-directed feature activity flags."""

    lexical: bool
    fuzzy: bool
    structured: bool
    price: bool


@dataclass(frozen=True, slots=True)
class Evidence:
    """Candidate evidence bits and structured match ratio."""

    lexical: Decimal
    fuzzy: Decimal
    structured: Decimal
    price: Decimal


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Raw and six-decimal values used by the total ordering."""

    lexical_raw: Decimal
    fuzzy_raw: Decimal
    structured_raw: Decimal | None
    price_raw: Decimal | None
    denominator: Decimal
    score_raw: Decimal | None
    coverage_raw: Decimal | None
    price_distance_raw: Decimal | None
    lexical: Decimal
    fuzzy: Decimal
    structured: Decimal | None
    price: Decimal | None
    score: Decimal | None
    coverage: Decimal | None
    price_distance: Decimal | None
    activity: Activity
    evidence: Evidence
