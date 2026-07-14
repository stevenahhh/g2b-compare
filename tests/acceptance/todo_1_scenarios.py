from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

import pytest
from pydantic import SecretStr, ValidationError

from g2b_compare.config import (
    G2B_API_BASE_URL,
    AppSettings,
    ProductionBase,
    SyncSettings,
)
from g2b_compare.errors import G2BCompareError
from g2b_compare.paths import validate_source_inventory
from tests.acceptance.todo_1_e0_cases import (
    run_e0_scenario,
    validate_happy_e0,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

type Scenario = Literal[
    "missing-source-artifact",
    "missing-hash-baseline",
    "unexpected-source-count",
    "missing-sync-key",
    "public-bind",
    "arbitrary-host",
    "http-base",
    "bad-budget",
    "e0-missing-file",
    "e0-schema",
    "e0-count",
    "e0-stratum",
    "e0-hash",
]
type SourceConfigScenario = Literal[
    "missing-source-artifact",
    "missing-hash-baseline",
    "unexpected-source-count",
    "missing-sync-key",
    "public-bind",
    "arbitrary-host",
    "http-base",
    "bad-budget",
]


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


@dataclass(frozen=True, slots=True)
class HappyObservation:
    inventory_count: int
    bind_host: str
    e0_count: int
    secret: str
    sync_repr: str


SCENARIOS: tuple[Scenario, ...] = (
    "missing-source-artifact",
    "missing-hash-baseline",
    "unexpected-source-count",
    "missing-sync-key",
    "public-bind",
    "arbitrary-host",
    "http-base",
    "bad-budget",
    "e0-missing-file",
    "e0-schema",
    "e0-count",
    "e0-stratum",
    "e0-hash",
)


def run_happy(workspace_root: Path, temp_root: Path) -> HappyObservation:
    secret = bytes.fromhex("746f646f2d312d64756d6d792d6b6579").decode()
    e0_count = validate_happy_e0(temp_root)
    inventory = validate_source_inventory(workspace_root)
    app = AppSettings()
    sync = SyncSettings(service_key=SecretStr(secret))
    return HappyObservation(
        inventory_count=inventory.count,
        bind_host=app.bind_host,
        e0_count=e0_count,
        secret=secret,
        sync_repr=repr(sync),
    )


def observe_failure(
    scenario: Scenario,
    temp_root: Path,
    monkeypatch: MonkeyPatch,
) -> FailureObservation:
    try:
        _run_failure_scenario(scenario, temp_root, monkeypatch)
    except (G2BCompareError, ValidationError) as error:
        return FailureObservation(
            assertion_class=type(error).__name__,
            message=str(error),
        )
    pytest.fail(f"scenario did not fail: {scenario}")


def _run_failure_scenario(
    scenario: Scenario,
    temp_root: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    match scenario:
        case (
            "missing-source-artifact"
            | "missing-hash-baseline"
            | "unexpected-source-count"
            | "missing-sync-key"
            | "public-bind"
            | "arbitrary-host"
            | "http-base"
            | "bad-budget"
        ):
            _run_source_config_scenario(scenario, temp_root, monkeypatch)
        case "e0-missing-file" | "e0-schema" | "e0-count" | "e0-stratum" | "e0-hash":
            run_e0_scenario(scenario, temp_root)
        case _:
            assert_never(scenario)


def _run_source_config_scenario(
    scenario: SourceConfigScenario,
    temp_root: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    source_paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    match scenario:
        case "missing-source-artifact":
            _ = validate_source_inventory(temp_root, source_paths, Path("hashes"))
        case "missing-hash-baseline":
            for source_path in source_paths:
                _ = (temp_root / source_path).write_bytes(b"source")
            _ = validate_source_inventory(temp_root, source_paths, Path("hashes"))
        case "unexpected-source-count":
            _ = validate_source_inventory(
                temp_root,
                source_paths[:3],
                Path("hashes"),
            )
        case "missing-sync-key":
            monkeypatch.delenv("G2B_SERVICE_KEY", raising=False)
            _ = SyncSettings.model_validate({})
        case "public-bind":
            _ = AppSettings.model_validate({"bind_host": str(ipaddress.IPv4Address(0))})
        case "arbitrary-host":
            _ = AppSettings.model_validate({"bind_host": "example.invalid"})
        case "http-base":
            _ = ProductionBase.model_validate(
                {"url": G2B_API_BASE_URL.replace("https://", "http://")}
            )
        case "bad-budget":
            _ = AppSettings(daily_api_budget=0)
        case _:
            assert_never(scenario)
