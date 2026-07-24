"""Exact ranking and parser metrics for held-out E0 evaluation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, override

SIX_PLACES: Final = Decimal("0.000001")
TOP_K: Final = 3
RELEVANT_LABEL: Final = 2
DCG_DISCOUNTS: Final = (
    Decimal(1),
    Decimal("1.584962500721156"),
    Decimal(2),
)
LABEL_GAINS: Final = (0, 1, 3, 7)
DUPLICATE_CANDIDATE: Final = "duplicate candidate id"
EMPTY_ANCHORS: Final = "empty anchor population"
SemanticTuple = tuple[
    str,
    str,
    str,
    str,
    str,
    str | None,
    str | None,
]


@dataclass(frozen=True, slots=True)
class EvaluationMetricError(ValueError):
    """Reject an evaluation population that cannot produce honest metrics."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class RankingItem:
    """One judged candidate and the score assigned by an evaluated ranker."""

    candidate_id: str
    label: int
    score: Decimal | None


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    """Macro-compatible metrics for one anchor or an anchor population."""

    precision_at_3: Decimal
    recall_at_3: Decimal
    hit_at_3: Decimal
    ndcg_at_3: Decimal


@dataclass(frozen=True, slots=True)
class ParserUnit:
    """One exact UTF-8 byte range and normalized semantic tuple."""

    row_id: str
    start_byte: int
    end_byte: int
    semantic: SemanticTuple


@dataclass(frozen=True, slots=True)
class ParserMetrics:
    """Micro-aggregated parser unit counts and rates."""

    true_positive: int
    false_positive: int
    false_negative: int
    precision: Decimal
    recall: Decimal


def ranking_metrics(rows: tuple[RankingItem, ...]) -> RankingMetrics:
    """Calculate top-three relevance and graded-gain metrics for one anchor."""
    identities = {row.candidate_id for row in rows}
    if len(identities) != len(rows):
        raise EvaluationMetricError(DUPLICATE_CANDIDATE)
    ordered = sorted(
        rows,
        key=lambda row: (
            row.score is None,
            -(row.score or Decimal(0)),
            row.candidate_id.encode(),
        ),
    )
    top = ordered[:TOP_K]
    top_relevant = sum(row.label >= RELEVANT_LABEL for row in top)
    all_relevant = sum(row.label >= RELEVANT_LABEL for row in rows)
    precision = Decimal(top_relevant) / Decimal(TOP_K)
    recall = (
        Decimal(top_relevant) / Decimal(all_relevant)
        if all_relevant > 0
        else Decimal(0)
    )
    hit = Decimal(all_relevant > 0 and top_relevant > 0)
    dcg = _dcg(tuple(row.label for row in top))
    ideal = _dcg(tuple(sorted((row.label for row in rows), reverse=True)[:TOP_K]))
    ndcg = dcg / ideal if ideal > 0 else Decimal(0)
    return RankingMetrics(
        _quantize(precision),
        _quantize(recall),
        _quantize(hit),
        _quantize(ndcg),
    )


def macro_ranking_metrics(rows: tuple[RankingMetrics, ...]) -> RankingMetrics:
    """Average already per-anchor metrics without pair-count weighting."""
    if not rows:
        raise EvaluationMetricError(EMPTY_ANCHORS)
    count = Decimal(len(rows))
    return RankingMetrics(
        *(
            _quantize(sum(values, Decimal(0)) / count)
            for values in (
                (row.precision_at_3 for row in rows),
                (row.recall_at_3 for row in rows),
                (row.hit_at_3 for row in rows),
                (row.ndcg_at_3 for row in rows),
            )
        )
    )


def parser_metrics(
    gold: tuple[ParserUnit, ...],
    predictions: tuple[ParserUnit, ...],
) -> ParserMetrics:
    """Greedily match identical parser units and count duplicate predictions."""
    gold_counts = Counter(gold)
    prediction_counts = Counter(predictions)
    true_positive = sum(
        min(count, prediction_counts.get(unit, 0))
        for unit, count in gold_counts.items()
    )
    false_positive = len(predictions) - true_positive
    false_negative = len(gold) - true_positive
    precision = _rate(true_positive, true_positive + false_positive)
    recall = _rate(true_positive, true_positive + false_negative)
    return ParserMetrics(
        true_positive,
        false_positive,
        false_negative,
        precision,
        recall,
    )


def _dcg(labels: tuple[int, ...]) -> Decimal:
    return sum(
        (
            Decimal(LABEL_GAINS[label]) / discount
            for label, discount in zip(labels, DCG_DISCOUNTS, strict=False)
        ),
        Decimal(0),
    )


def _rate(numerator: int, denominator: int) -> Decimal:
    return (
        _quantize(Decimal(numerator) / Decimal(denominator))
        if denominator > 0
        else Decimal(0)
    )


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN)
