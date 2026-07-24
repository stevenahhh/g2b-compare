"""Hand-verifiable ranking and parser evaluation contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from g2b_compare.evaluation.metrics import (
    ParserUnit,
    RankingItem,
    macro_ranking_metrics,
    parser_metrics,
    ranking_metrics,
)


def test_ranking_metrics_use_label_two_as_relevant_and_standard_dcg() -> None:
    rows = (
        RankingItem("A", 3, Decimal("0.9")),
        RankingItem("B", 1, Decimal("0.8")),
        RankingItem("C", 2, Decimal("0.7")),
        RankingItem("D", 2, Decimal("0.6")),
    )

    result = ranking_metrics(rows)

    assert result.precision_at_3 == Decimal("0.666667")
    assert result.recall_at_3 == Decimal("0.666667")
    assert result.hit_at_3 == Decimal("1.000000")
    assert result.ndcg_at_3 == Decimal("0.878583")


def test_ranking_metrics_zero_relevant_denominator_keeps_graded_ndcg() -> None:
    result = ranking_metrics(
        (
            RankingItem("A", 1, Decimal("0.9")),
            RankingItem("B", 0, None),
        )
    )

    assert result.recall_at_3 == 0
    assert result.hit_at_3 == 0
    assert result.ndcg_at_3 == Decimal("1.000000")


def test_macro_metrics_average_per_anchor_not_pairs() -> None:
    result = macro_ranking_metrics(
        (
            ranking_metrics((RankingItem("A", 3, Decimal(1)),)),
            ranking_metrics(
                (
                    RankingItem("B", 0, Decimal(1)),
                    RankingItem("C", 0, Decimal(0)),
                    RankingItem("D", 0, None),
                )
            ),
        )
    )

    assert result.precision_at_3 == Decimal("0.166666")
    assert result.hit_at_3 == Decimal("0.500000")


def test_parser_metrics_match_utf8_byte_range_and_semantics_one_to_one() -> None:
    semantic = ("8000000", "pixel", "resolution", "resolution", "eq", None, None)
    gold = (ParserUnit("R1", 0, 13, semantic),)
    predictions = (
        ParserUnit("R1", 0, 13, semantic),
        ParserUnit("R1", 0, 13, semantic),
        ParserUnit("R1", 0, 12, semantic),
    )

    result = parser_metrics(gold, predictions)

    assert (result.true_positive, result.false_positive, result.false_negative) == (
        1,
        2,
        0,
    )
    assert result.precision == Decimal("0.333333")
    assert result.recall == Decimal("1.000000")


def test_ranking_metrics_reject_duplicate_candidate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate candidate"):
        _ = ranking_metrics(
            (
                RankingItem("A", 3, Decimal(1)),
                RankingItem("A", 2, Decimal(0)),
            )
        )
