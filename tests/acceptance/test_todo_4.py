"""Todo 4 acceptance contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.normalize import normalize_text, parse_specs
from tests.acceptance.todo_4_scenarios import SCENARIOS, Scenario, observe_failure


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message_regex: str


def _registry() -> dict[str, FailureContract]:
    return TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )


def test_happy() -> None:
    registry = _registry()
    contract = registry["todo-4/happy"]
    assert contract.assertion_class == "Todo4NotImplementedError"
    assert contract.message_regex == "Todo 4 normalization module.*not implemented"
    assert normalize_text("영상감시장치").tokens == ("영상감시장치",)
    assert parse_specs("800만화소").semantics[0].value == 8_000_000
    assert parse_specs("8MP").semantics[0].canonical_unit == "pixel"
    dimension = parse_specs("3840\u00d72160")
    assert [item.attribute_key for item in dimension.semantics] == [
        "width",
        "height",
        "total-pixel",
    ]
    assert parse_specs("4배줌").semantics[0].attribute_key == "zoom"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    contract = _registry()[f"todo-4/{scenario}"]
    observation = observe_failure(scenario, tmp_path)
    assert observation.assertion_class == contract.assertion_class
    assert re.search(contract.message_regex, observation.message) is not None
