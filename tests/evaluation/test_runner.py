"""Strict held-out evaluation runner contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from g2b_compare.evaluation.metrics import ParserMetrics, RankingMetrics
from g2b_compare.evaluation.runner import (
    EvaluationThresholdError,
    HeldOutReport,
    run_strict_evaluation,
    validate_held_out,
)
from g2b_compare.evaluation.runner_artifacts import EvaluationArtifactError

from .strict_runner_fixture import load_rows, rewrite_rows, strict_runner_paths

if TYPE_CHECKING:
    from pathlib import Path


def _ranking(precision: str, ndcg: str) -> RankingMetrics:
    return RankingMetrics(
        precision_at_3=Decimal(precision),
        recall_at_3=Decimal("0.8"),
        hit_at_3=Decimal(1),
        ndcg_at_3=Decimal(ndcg),
    )


def test_held_out_thresholds_accept_exact_boundary() -> None:
    report = HeldOutReport(
        anchor_count=40,
        category_leakage=0,
        null_slot_rate=Decimal(0),
        judged_pool_determinism=Decimal(1),
        full_v1=_ranking("0.80", "0.73"),
        lexical_only=_ranking("0.79", "0.70"),
        parser=ParserMetrics(98, 2, 10, Decimal("0.98"), Decimal("0.907407")),
    )

    assert validate_held_out(report) == report


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("parser-precision", "parser precision"),
        ("parser-recall", "parser recall"),
        ("ranking-regression", "full-v1 precision"),
        ("lexical-baseline-drift", "lexical precision"),
        ("category-leak", "category leakage"),
        ("judged-pool-full-v1", "judged pool"),
    ],
)
def test_held_out_thresholds_fail_closed(field: str, message: str) -> None:
    report = HeldOutReport(
        anchor_count=40,
        category_leakage=1 if field == "category-leak" else 0,
        null_slot_rate=Decimal(0),
        judged_pool_determinism=(
            Decimal("0.99") if field == "judged-pool-full-v1" else Decimal(1)
        ),
        full_v1=_ranking(
            "0.79" if field == "ranking-regression" else "0.80",
            "0.729" if field == "lexical-baseline-drift" else "0.73",
        ),
        lexical_only=_ranking(
            "0.78" if field == "lexical-baseline-drift" else "0.79",
            "0.70",
        ),
        parser=ParserMetrics(
            98,
            3 if field == "parser-precision" else 2,
            11 if field == "parser-recall" else 10,
            Decimal("0.970297") if field == "parser-precision" else Decimal("0.98"),
            Decimal("0.899083") if field == "parser-recall" else Decimal("0.907407"),
        ),
    )

    with pytest.raises(EvaluationThresholdError, match=message):
        _ = validate_held_out(report)


def test_strict_runner_reads_external_gold_and_actual_predictions(
    tmp_path: Path,
) -> None:
    paths = strict_runner_paths(tmp_path)

    report = run_strict_evaluation(paths)

    assert report.anchor_count == 40
    assert report.full_v1.precision_at_3 == Decimal("1.000000")
    assert report.full_v1.ndcg_at_3 == Decimal("1.000000")
    assert report.parser.precision == Decimal("1.000000")
    assert report.parser.recall == Decimal("1.000000")


def test_strict_runner_rejects_prediction_outside_exported_pool(
    tmp_path: Path,
) -> None:
    paths = strict_runner_paths(tmp_path)
    rows = load_rows(paths.full_v1_predictions)
    rows[0]["candidate_id"] = "unjudged-candidate"
    rewrite_rows(paths.full_v1_predictions, rows)

    with pytest.raises(EvaluationArtifactError, match="judged pool mismatch"):
        _ = run_strict_evaluation(paths)


def test_strict_runner_measures_parser_prediction_misses(
    tmp_path: Path,
) -> None:
    paths = strict_runner_paths(tmp_path)
    rows = load_rows(paths.parser_predictions)
    for index, row in enumerate(rows):
        if index % 3 == 0 and row.get("spans"):
            row["spans"] = []
    rewrite_rows(paths.parser_predictions, rows)

    with pytest.raises(EvaluationThresholdError, match="parser recall"):
        _ = run_strict_evaluation(paths)
