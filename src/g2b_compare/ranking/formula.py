"""Implement Ranking formula v1 with Decimal half-even output."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final

from .explain import Activity, Evidence, ScoreBreakdown

RANKING_VERSION: Final = "v1"
SIX_PLACES: Final = Decimal("0.000001")
WEIGHT_L: Final = Decimal("0.35")
WEIGHT_F: Final = Decimal("0.20")
WEIGHT_U: Final = Decimal("0.35")
WEIGHT_P: Final = Decimal("0.10")
DECAY: Final = Decimal("1.25")


@dataclass(frozen=True, slots=True)
class FormulaInput:
    """Pair features and anchor-directed activity for one score."""

    lexical: Decimal
    fuzzy: Decimal
    structured: Decimal | None
    price: Decimal | None
    price_distance: Decimal | None
    anchor_option_present: bool
    candidate_option_present: bool
    anchor_spec_count: int
    matched_anchor_count: int
    anchor_price_active: bool
    candidate_price_comparable: bool


def value_similarity(left: Decimal, right: Decimal) -> Decimal | None:
    """Return symmetric log-ratio decay for two positive values."""
    if left <= 0 or right <= 0:
        return None
    with localcontext() as context:
        context.prec = 40
        distance = (max(left, right) / min(left, right)).ln()
        return (-(distance / DECAY.ln())).exp()


def log_distance(left: Decimal, right: Decimal) -> Decimal | None:
    """Return the raw absolute log ratio for positive values."""
    if left <= 0 or right <= 0:
        return None
    with localcontext() as context:
        context.prec = 40
        return (max(left, right) / min(left, right)).ln()


def range_similarity(
    left: tuple[Decimal, Decimal], right: tuple[Decimal, Decimal]
) -> Decimal | None:
    """Average lower and upper similarity for two finite ranges."""
    lower = value_similarity(left[0], right[0])
    upper = value_similarity(left[1], right[1])
    if lower is None or upper is None:
        return None
    return (lower + upper) / 2


def quantize_score(value: Decimal) -> Decimal:
    """Quantize one ranking value to six places using round-half-even."""
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN)


def score_formula(features: FormulaInput) -> ScoreBreakdown:
    """Calculate score, coverage, and exact ordering components."""
    activity = Activity(
        lexical=features.anchor_option_present,
        fuzzy=features.anchor_option_present,
        structured=features.anchor_spec_count > 0,
        price=features.anchor_price_active,
    )
    denominator = _denominator(activity)
    matched_ratio = (
        Decimal(features.matched_anchor_count) / Decimal(features.anchor_spec_count)
        if features.anchor_spec_count > 0
        else Decimal(0)
    )
    evidence = Evidence(
        lexical=Decimal(features.candidate_option_present),
        fuzzy=Decimal(features.candidate_option_present),
        structured=matched_ratio,
        price=Decimal(features.candidate_price_comparable),
    )
    score = _score(features, activity, denominator)
    coverage = _coverage(activity, evidence, denominator)
    return ScoreBreakdown(
        lexical_raw=features.lexical,
        fuzzy_raw=features.fuzzy,
        structured_raw=features.structured,
        price_raw=features.price,
        denominator=denominator,
        score_raw=score,
        coverage_raw=coverage,
        price_distance_raw=features.price_distance,
        lexical=quantize_score(features.lexical),
        fuzzy=quantize_score(features.fuzzy),
        structured=_quantize_optional(features.structured),
        price=_quantize_optional(features.price),
        score=_quantize_optional(score),
        coverage=_quantize_optional(coverage),
        price_distance=_quantize_optional(features.price_distance),
        activity=activity,
        evidence=evidence,
    )


def _denominator(activity: Activity) -> Decimal:
    return (
        WEIGHT_L * Decimal(activity.lexical)
        + WEIGHT_F * Decimal(activity.fuzzy)
        + WEIGHT_U * Decimal(activity.structured)
        + WEIGHT_P * Decimal(activity.price)
    )


def _score(
    features: FormulaInput, activity: Activity, denominator: Decimal
) -> Decimal | None:
    if denominator == 0:
        return None
    structured = features.structured or Decimal(0)
    price = features.price or Decimal(0)
    numerator = (
        WEIGHT_L * Decimal(activity.lexical) * features.lexical
        + WEIGHT_F * Decimal(activity.fuzzy) * features.fuzzy
        + WEIGHT_U * Decimal(activity.structured) * structured
        + WEIGHT_P * Decimal(activity.price) * price
    )
    return numerator / denominator


def _coverage(
    activity: Activity, evidence: Evidence, denominator: Decimal
) -> Decimal | None:
    if denominator == 0:
        return None
    numerator = (
        WEIGHT_L * Decimal(activity.lexical) * evidence.lexical
        + WEIGHT_F * Decimal(activity.fuzzy) * evidence.fuzzy
        + WEIGHT_U * Decimal(activity.structured) * evidence.structured
        + WEIGHT_P * Decimal(activity.price) * evidence.price
    )
    return numerator / denominator


def _quantize_optional(value: Decimal | None) -> Decimal | None:
    return None if value is None else quantize_score(value)
