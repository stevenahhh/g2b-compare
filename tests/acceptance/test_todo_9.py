from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.materialize.scenarios import observe_failure, run_happy

SCENARIOS = (
    "conflict-name",
    "missing-detail",
    "zero-price",
    "negative-price",
    "mixed-unit",
    "partial-attribute",
    "option-first-nonempty-fallback",
    "attribute-order",
    "segment-delimiter",
    "segment-duplicate",
    "all-empty-option",
    "option-byte-sha",
    "one-offer-removed",
    "unmatched-registration-cancel",
)


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


def test_happy() -> None:
    result = run_happy()

    assert result.product_count == 1
    assert result.offer_count == 3
    assert result.price_won == 1100000
    assert result.coverage == "1"
    assert (
        result.option_sha
        == "5a41360a3223586e780528b7847f72034b9db43033d9d722c2b1b40527daaa05"
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(scenario: str) -> None:
    registry = TypeAdapter(dict[str, FailureContract]).validate_json(
        Path("tests/acceptance/expected-failures.json").read_bytes()
    )
    expected = registry[f"todo-9/{scenario}"]

    observation = observe_failure(scenario)

    assert observation.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observation.message) is not None
