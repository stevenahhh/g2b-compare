"""Todo15 exact acceptance-node contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.acceptance.todo_15_scenarios import (
    Scenario,
    observe_failure,
    validate_happy,
)

SCENARIOS: tuple[Scenario, ...] = (
    "slow-search",
    "slow-cache",
    "slow-html",
    "slow-startup",
    "cache-disabled",
    "perf-field-drift",
    "perf-overlap-rule",
    "query-selection-drift",
    "thread-env-missing",
    "corpus-hash-mismatch",
    "category-leak",
    "secret-runtime",
    "source-mutation",
    "insufficient-gold",
    "wrong-anchor-count",
    "wrong-candidate-count",
    "missing-gold-manifest",
    "gold-hash-mismatch",
    "single-assessor",
    "assessor-not-independent",
    "blinded-order-drift",
    "incomplete-double-label",
    "missing-adjudication",
    "invalid-adjudication",
    "split-count",
    "split-leakage",
    "parser-gold-count",
    "parser-negative-row",
    "parser-compound-span-count",
    "parser-byte-boundary",
    "parser-semantic-mismatch",
    "parser-duplicate-prediction",
    "parser-precision",
    "parser-recall",
    "metric-relevance-threshold",
    "metric-dcg-formula",
    "metric-macro-aggregation",
    "lexical-baseline-drift",
    "non-heldout-threshold",
    "ranking-regression",
    "misleading-success-output",
    "parser-dimension-semantic-count",
    "parser-shared-span-semantics",
    "parser-semantic-total",
    "evaluation-unjudged-candidate",
    "judged-pool-full-v1",
    "judged-pool-lexical",
)


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def _registry() -> dict[str, FailureContract]:
    return TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )


def test_registry_has_exact_todo_15_ids() -> None:
    expected = {f"todo-15/{scenario}" for scenario in SCENARIOS}
    actual = {key for key in _registry() if key.startswith("todo-15/")}

    assert actual == expected
    assert len(actual) == 47


def test_happy(tmp_path: Path) -> None:
    validate_happy(tmp_path)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_has_exact_typed_reason(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    observation = observe_failure(scenario, tmp_path)
    expected = _registry()[f"todo-15/{scenario}"]

    assert observation.assertion_class == expected.assertion_class
    assert re.fullmatch(expected.message_regex, observation.message) is not None
