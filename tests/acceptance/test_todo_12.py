from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.acceptance.todo_12_scenarios import (
    SCENARIOS,
    observe_failure,
    run_happy,
)


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def _registry() -> dict[str, FailureContract]:
    return TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )


def test_registry_has_exact_todo_12_ids() -> None:
    expected = {f"todo-12/{scenario}" for scenario in SCENARIOS}

    actual = {key for key in _registry() if key.startswith("todo-12/")}

    assert actual == expected
    assert len(actual) == 54


def test_happy(tmp_path: Path) -> None:
    result = run_happy(tmp_path)

    assert result.active_ready
    assert result.exact_cache_rows == 12
    assert result.cached_uncached_equal
    assert result.canonical_json_equal
    assert result.category_auto_selected
    assert result.price_flags == (True, True, True, False)
    assert result.provenance_complete
    assert result.request_pin_stable
    assert result.search_read_only


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: str, tmp_path: Path
) -> None:
    expected = _registry()[f"todo-12/{scenario}"]

    observed = observe_failure(scenario, tmp_path)

    assert observed.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observed.message) is not None
