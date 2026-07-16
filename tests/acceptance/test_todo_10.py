from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.search.todo10_scenarios import SCENARIOS, observe_failure, run_happy


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def test_happy() -> None:
    result = run_happy()

    assert result.members == 8
    assert result.exact_ids == ("P-01", "P-02", "P-03")
    assert result.active_release_unchanged
    assert result.release_graph_preserved_on_success
    assert result.release_graph_preserved_on_failure
    assert result.query_paths_pure


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(scenario: str) -> None:
    registry = TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )
    expected = registry[f"todo-10/{scenario}"]

    observed = observe_failure(scenario)

    assert observed.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observed.message) is not None
