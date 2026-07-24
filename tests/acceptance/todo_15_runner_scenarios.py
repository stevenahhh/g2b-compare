"""Artifact-backed Todo15 acceptance paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.evaluation.contracts import Todo15ContractError
from g2b_compare.evaluation.runner import (
    EvaluationThresholdError,
    run_strict_evaluation,
)
from g2b_compare.evaluation.runner_artifacts import EvaluationArtifactError
from tests.evaluation.strict_runner_fixture import (
    load_rows,
    rewrite_rows,
    strict_runner_paths,
)

if TYPE_CHECKING:
    from pathlib import Path


def validate_strict_runner_happy(temp_root: Path) -> None:
    report = run_strict_evaluation(strict_runner_paths(temp_root / "strict-runner"))
    if report.anchor_count != 40:
        detail = "wrong-anchor-count"
        raise Todo15ContractError(detail)


def run_strict_runner_failure(scenario: str, temp_root: Path) -> None:
    paths = strict_runner_paths(temp_root / scenario)
    if scenario == "parser-recall":
        rows = load_rows(paths.parser_predictions)
        for index, row in enumerate(rows):
            if index % 3 == 0 and row.get("spans"):
                row["spans"] = []
        rewrite_rows(paths.parser_predictions, rows)
    else:
        rows = load_rows(paths.full_v1_predictions)
        if scenario == "evaluation-unjudged-candidate":
            rows[0]["candidate_id"] = "unjudged-candidate"
        else:
            for row in rows:
                row["score"] = "0"
        rewrite_rows(paths.full_v1_predictions, rows)
    try:
        _ = run_strict_evaluation(paths)
    except (EvaluationArtifactError, EvaluationThresholdError) as error:
        detail = f"{scenario}: {error}"
        raise Todo15ContractError(detail) from None
