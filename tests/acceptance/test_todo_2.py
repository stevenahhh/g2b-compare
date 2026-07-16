from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.acceptance.todo_2_scenarios import observe_failure, run_happy


class ExpectedFailure(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    assertion_class: str
    message_regex: str


SCENARIOS = (
    "missing-attribute-quota-row",
    "quota-unknown",
    "quota-row-not-approved",
    "low-quota-zero-call",
    "probe-budget-below-three",
    "missing-key",
    "attribute-call-before-quota",
    "401-text",
    "200-wrong-content-type",
    "malformed-envelope",
    "attribute-http-only",
    "redirect-response-zero-followup",
    "all-discovery-empty",
    "retry-leaves-no-verification-budget",
    "verification-empty",
    "probe-call-6",
    "stable-key-missing",
    "stable-key-duplicate",
    "limit-unproven",
    "provisional-schema-not-strict",
    "unverified-share-field",
    "share-preflight-redirect",
)

FAILURE_REGISTRY = TypeAdapter(dict[str, ExpectedFailure]).validate_json(
    Path(__file__).with_name("expected-failures.json").read_bytes()
)


def test_happy() -> None:
    # Given: the Todo 2 capture scenario surface.
    # When: the complete six-operation contract is captured.
    observation = run_happy()

    # Then: every operation reaches the strict VERIFIED state.
    assert len(observation.captures) == 6
    assert observation.http_calls == 18
    assert all(
        type(capture.manifest.state).__name__ == "VerifiedState"
        for capture in observation.captures
    )
    assert all(
        capture.manifest == capture.manifest_history[-1]
        and capture.transitions
        == tuple(manifest.state.phase for manifest in capture.manifest_history)
        for capture in observation.captures
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(scenario: str) -> None:
    # Given: one Todo 2 adversarial contract scenario.
    # When: the production capture boundary observes it.
    observation = observe_failure(scenario)

    # Then: the concrete boundary outcome matches its machine-readable contract.
    expected = FAILURE_REGISTRY[f"todo-2/{scenario}"]
    assert observation.assertion_class == expected.assertion_class
    assert re.search(expected.message_regex, observation.message)
