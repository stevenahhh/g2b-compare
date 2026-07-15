from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Final, Literal

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
REGISTRY = Path("tests/acceptance/expected-failures.json")
RED_PROVENANCE = Path("tests/acceptance/fixtures/todo3-red-provenance.json")
RED_PROVENANCE_SHA256: Final = (
    "df2619717995ca450bda7c2d0d131dd979de857d9fa5fd14c4bafac75c89ebc0"
)
RED_NODES_SHA256: Final = (
    "653f126a0c10325f9ccdd7ffc9f2c0d5f65b596df804dda62c618b6b152c5564"
)
SYNTHETIC_LIMITATION: Final = (
    "The source JUnit was produced by an environment-gated synthetic harness; "
    "it records registry contracts but does not prove production scenario-boundary "
    "failures."
)
SCENARIO_TEST_NAME: Final = "test_failure_scenario_matches_registry_contract"


class FailureContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message_regex: str


class RedFailureRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    test_name: str
    assertion_class: str
    message: str
    contract_sha256: str


class RedCaptureReceipt(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    kind: Literal["synthetic-contract-receipt"]
    feature_base_commit: Literal["bd299c0d5db284ec2df23f1a29792aba2e4c6c34"]
    recorded_commit: Literal["5453599ea2db3d03dd46d0ed41684a31a963162e"]
    source_junit_sha256: Literal[
        "d933a0d0d0d7f54da60d3c5dd5692dff4d057bfd0fdb227329821612d9d1bf91"
    ]
    command: str
    exit_code: Literal[1]
    limitation: str


class RedProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["1"]
    capture: RedCaptureReceipt
    nodes_sha256: str
    nodes: dict[str, RedFailureRecord]


@pytest.fixture(scope="session")
def _audit_preserved_red_contracts() -> None:
    encoded = RED_PROVENANCE.read_bytes()
    tampered = encoded.replace(b'"exit_code": 1', b'"exit_code": 0', 1)
    assert tampered != encoded
    with pytest.raises(AssertionError, match="receipt SHA mismatch"):
        _audit_red_provenance(tampered)
    _audit_red_provenance(encoded)


pytestmark = pytest.mark.usefixtures(_audit_preserved_red_contracts.__name__)


def test_happy(tmp_path: Path) -> None:
    # Given: the Todo 3 migration contract
    assert MIGRATION.is_file()
    # When: the complete successor and materialization lifecycle runs
    HAPPY_RUNNER(tmp_path)
    # Then: the real SQLite observables are asserted by the runner


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIOS)
def test_failure_scenario_matches_registry_contract(
    scenario: str,
    tmp_path: Path,
) -> None:
    # Given: one registered Todo 3 failure scenario
    runner = SCENARIO_RUNNERS[scenario]
    # When: its real temporary database/filesystem contract is exercised
    runner(tmp_path)
    # Then: its binary observable is asserted by the runner


def _failure_contracts() -> dict[str, FailureContract]:
    return TypeAdapter(dict[str, FailureContract]).validate_json(REGISTRY.read_bytes())


def _audit_red_provenance(encoded: bytes) -> None:
    normalized = encoded.replace(b"\r\n", b"\n")
    assert sha256(normalized).hexdigest() == RED_PROVENANCE_SHA256, (
        "RED provenance receipt SHA mismatch"
    )
    provenance = RedProvenance.model_validate_json(encoded)
    assert provenance.capture.limitation == SYNTHETIC_LIMITATION
    expected_keys = {"todo-3/happy"} | {f"todo-3/{scenario}" for scenario in SCENARIOS}
    assert set(provenance.nodes) == expected_keys
    canonical_nodes = {
        key: {
            "assertion_class": failure.assertion_class,
            "contract_sha256": failure.contract_sha256,
            "message": failure.message,
            "test_name": failure.test_name,
        }
        for key, failure in provenance.nodes.items()
    }
    canonical = json.dumps(
        canonical_nodes,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert provenance.nodes_sha256 == RED_NODES_SHA256
    assert sha256(canonical).hexdigest() == RED_NODES_SHA256
    contracts = _failure_contracts()
    for registry_key, failure in provenance.nodes.items():
        contract = contracts[registry_key]
        expected_name = (
            "test_happy"
            if registry_key == "todo-3/happy"
            else f"{SCENARIO_TEST_NAME}[{registry_key.removeprefix('todo-3/')}]"
        )
        assert failure.test_name == expected_name
        assert failure.assertion_class == contract.assertion_class
        assert re.search(contract.message_regex, failure.message) is not None
        digest_input = (
            f"{registry_key}\0{failure.test_name}\0"
            f"{failure.assertion_class}\0{failure.message}"
        )
        assert sha256(digest_input.encode()).hexdigest() == failure.contract_sha256
