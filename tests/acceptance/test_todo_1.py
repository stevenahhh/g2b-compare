from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.acceptance.todo_1_scenarios import (
    SCENARIOS,
    Scenario,
    observe_failure,
    run_happy,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message_regex: str


def test_happy(tmp_path: Path) -> None:
    # Given: immutable sources, loopback settings, a dummy key, and valid E0 data
    workspace_root = Path.cwd()

    # When: every Todo 1 boundary validates real inputs
    observation = run_happy(workspace_root, tmp_path)

    # Then: the complete local bootstrap contract is observable
    assert (
        observation.inventory_count,
        observation.bind_host,
        observation.e0_count,
    ) == (4, "127.0.0.1", 1)
    assert observation.secret not in observation.sync_repr


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a registered failure contract and its real boundary input
    registry = TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )
    contract = registry[f"todo-1/{scenario}"]

    # When: the real production boundary rejects the scenario
    observation = observe_failure(scenario, tmp_path, monkeypatch)

    # Then: the actual exception class and message satisfy the registry
    assert observation.assertion_class == contract.assertion_class
    assert re.search(contract.message_regex, observation.message) is not None
