from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.ranking.scenarios import SCENARIOS, observe_failure, run_happy


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def test_happy() -> None:
    result = run_happy()

    assert result.identifiers == ("B", "C", "D")
    assert result.score > 0
    assert result.coverage == 1
    assert result.exact_slots == 3


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(scenario: str) -> None:
    registry = TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )
    expected = registry[f"todo-11/{scenario}"]

    observed = observe_failure(scenario)

    assert observed.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observed.message) is not None
