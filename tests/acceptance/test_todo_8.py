from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.contracts.quota import Operation
from tests.sync.todo8_acceptance import observe_failure, run_happy

SCENARIOS = (
    "unchanged-row-lost",
    "stale-attribute-target",
    "delivery-change-requeues-all",
    "changed-product-not-requeued",
    "missing-window-page",
    "duplicate-window-page",
    "changing-total",
    "retry-charged",
    "one-day-over-budget",
    "kst-boundary",
    "kill-staging",
    "release-pointer-changed",
    "materialization-created-by-sync",
    "explicit-cancel",
    "one-source-cancel",
    "absence-delta",
    "absence-full",
    "registration-key-mismatch",
)


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def test_happy(tmp_path: Path) -> None:
    database = tmp_path / "todo8.sqlite3"
    result = run_happy(database, date(2026, 7, 16))

    assert result.source_count == 5
    assert result.delivery_delta_carried == ("P-1",)
    assert result.partial_successor_pending == ("P-2",)
    assert result.resumed_digest == result.uninterrupted_digest
    assert result.release_before == result.release_after


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: str,
    tmp_path: Path,
) -> None:
    registry = TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )
    expected = registry[f"todo-8/{scenario}"]

    observation = observe_failure(
        scenario,
        tmp_path / f"{scenario}.sqlite3",
        datetime(2026, 7, 16, 0, 30, tzinfo=UTC),
    )

    assert observation.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observation.message) is not None
    assert "serviceKey" not in json.dumps(observation.model_dump())
    assert observation.operation in tuple(item.value for item in Operation)[:5]
