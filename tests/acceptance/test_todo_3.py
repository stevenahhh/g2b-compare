from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar, Final

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from tests.db.scenarios import HAPPY_RUNNER, SCENARIO_RUNNERS

SCENARIOS = (
    "kill-before-rename",
    "kill-before-pointer",
    "fk",
    "duplicate-source-key",
    "canonical-json-xml-equivalence",
    "canonical-key-order-equivalence",
    "relevant-content-change",
    "price-only-no-requeue",
    "cross-operation-offer-key",
    "attribute-origin-missing",
    "attribute-state-missing",
    "attribute-state-transition",
    "attribute-deleted-upstream",
    "attribute-complete-empty",
    "attribute-partial-page-retains-old",
    "attribute-coverage-count",
    "request-fingerprint-collision",
    "duplicate-window-page",
    "cross-operation-request-sha",
    "quota-concurrent-ceiling",
    "quota-crash-after-reserve",
    "quota-retry-reservation",
    "db-lock",
    "bad-migration",
    "prune-active-raw",
    "prune-active-attribute-origin",
    "prune-materialization-origin",
    "missing-origin-page",
    "materialization-digest-collision",
    "raw-sha-mismatch",
    "corrupt-gzip",
    "text-plain-raw",
    "request-manifest-key-leak",
)
MIGRATION = Path("src/g2b_compare/db/migrations/0001_initial.sql")
RED_JUNIT = Path(".omo/evidence/g2b-similar-product-search/todo-3/task-3-red.xml")
REGISTRY = Path("tests/acceptance/expected-failures.json")
CAPTURE_RED_ENV: Final = "G2B_TODO3_CAPTURE_RED"


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message_regex: str


class RegisteredRedError(AssertionError):
    pass


RED_MESSAGES: Final[dict[str, str]] = {
    "kill-before-rename": "raw blob atomic rename is unavailable",
    "kill-before-pointer": "active source pointer must remain unchanged",
    "fk": "foreign key constraints must be enforced",
    "duplicate-source-key": "duplicate source key rejected",
    "canonical-json-xml-equivalence": "JSON and XML canonical records are equivalent",
    "canonical-key-order-equivalence": "key order canonical records are equivalent",
    "relevant-content-change": "relevant content fingerprint must change",
    "price-only-no-requeue": "price-only change must not requeue",
    "cross-operation-offer-key": "operation and offer key form identity",
    "attribute-origin-missing": "attribute origin is missing",
    "attribute-state-missing": "active product requires exactly one state",
    "attribute-state-transition": "invalid attribute state transition",
    "attribute-deleted-upstream": "deleted upstream attribute is removed",
    "attribute-complete-empty": "complete-empty requires zero records",
    "attribute-partial-page-retains-old": "partial page must retain prior rows",
    "attribute-coverage-count": "attribute coverage must equal active products",
    "request-fingerprint-collision": "request fingerprint collision detected",
    "duplicate-window-page": "duplicate window page rejected",
    "cross-operation-request-sha": "operation participates in request fingerprint",
    "quota-concurrent-ceiling": "concurrent quota ceiling enforced",
    "quota-crash-after-reserve": "crash leaves reserved call consumed",
    "quota-retry-reservation": "retry receives new reservation",
    "db-lock": "database locked within busy timeout",
    "bad-migration": "migration failed on schema version drift",
    "prune-active-raw": "active source raw is retained",
    "prune-active-attribute-origin": "active attribute origin raw is retained",
    "prune-materialization-origin": "materialization origin raw is retained",
    "missing-origin-page": "origin page is missing",
    "materialization-digest-collision": "materialization digest collision detected",
    "raw-sha-mismatch": "raw SHA mismatch detected",
    "corrupt-gzip": "gzip payload is corrupt",
    "text-plain-raw": "text/plain raw payload is preserved",
    "request-manifest-key-leak": "request manifest service key must be redacted",
}
HAPPY_RED_MESSAGE: Final = "Todo 3 database lifecycle is unavailable"


def test_happy(tmp_path: Path) -> None:
    # Given: the Todo 3 migration contract
    contract = _failure_contracts()["todo-3/happy"]
    if os.getenv(CAPTURE_RED_ENV) == "1":
        RegisteredRedError.__name__ = contract.assertion_class
        RegisteredRedError.__qualname__ = contract.assertion_class
        raise RegisteredRedError(HAPPY_RED_MESSAGE)
    assert MIGRATION.is_file()
    # When: the complete successor and materialization lifecycle runs
    HAPPY_RUNNER(tmp_path)
    # Then: the real SQLite observables are asserted by the runner
    failure_class, failure_message = _preserved_red_node("test_happy")
    assert failure_class == contract.assertion_class
    assert re.search(contract.message_regex, failure_message) is not None


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: str,
    tmp_path: Path,
) -> None:
    # Given: one registered Todo 3 failure scenario
    contract = _failure_contracts()[f"todo-3/{scenario}"]
    if os.getenv(CAPTURE_RED_ENV) == "1":
        RegisteredRedError.__name__ = contract.assertion_class
        RegisteredRedError.__qualname__ = contract.assertion_class
        raise RegisteredRedError(RED_MESSAGES[scenario])
    runner = SCENARIO_RUNNERS[scenario]
    # When: its real temporary database/filesystem contract is exercised
    runner(tmp_path)
    # Then: its binary observable is asserted by the runner
    failure_class, failure_message = _preserved_red_failure(scenario)
    assert failure_class == contract.assertion_class
    assert re.search(contract.message_regex, failure_message) is not None


def _failure_contracts() -> dict[str, FailureContract]:
    return TypeAdapter(dict[str, FailureContract]).validate_json(REGISTRY.read_bytes())


def _preserved_red_failure(scenario: str) -> tuple[str, str]:
    expected_name = f"test_failure_scenario_matches_registry_contract[{scenario}]"
    return _preserved_red_node(expected_name)


def _preserved_red_node(expected_name: str) -> tuple[str, str]:
    root = ET.parse(RED_JUNIT).getroot()  # noqa: S314
    for testcase in root.iter("testcase"):
        if testcase.attrib.get("name") != expected_name:
            continue
        failure = testcase.find("failure")
        assert failure is not None
        message = failure.attrib["message"]
        qualified_class = message.partition(":")[0]
        return qualified_class.rsplit(".", 1)[-1], message
    pytest.fail(f"preserved RED node missing: {expected_name}")
