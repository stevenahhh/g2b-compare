"""Drive each Todo 4 failure contract through its real boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

import pytest
from openpyxl import Workbook

from g2b_compare.normalize import (
    AmbiguousNumberError,
    InvalidQuantityError,
    ParsedSpecs,
    RangeParseError,
    UnitAliasError,
    UnsupportedNumberError,
    WorkbookExternalLinkError,
    WorkbookFormulaError,
    WorkbookSourceHashError,
    inspect_workbook,
    normalize_text,
    parse_specs,
    verify_source_hash,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

type Scenario = Literal[
    "token-order",
    "protect-before-casefold",
    "mp-domain-case",
    "protected-decimal",
    "relation-boundary",
    "range-boundary",
    "sign-range-precedence",
    "pure-korean-unsupported",
    "zero",
    "negative",
    "broken-range",
    "si-case",
    "formula-error",
    "external-link",
    "ambiguous-number",
    "source-hash-change",
]
type BehaviorScenario = Literal[
    "token-order",
    "protect-before-casefold",
    "mp-domain-case",
    "protected-decimal",
    "relation-boundary",
    "range-boundary",
    "sign-range-precedence",
]
type ParserErrorScenario = Literal[
    "pure-korean-unsupported",
    "zero",
    "negative",
    "broken-range",
    "si-case",
    "ambiguous-number",
]
type WorkbookErrorScenario = Literal[
    "formula-error",
    "external-link",
    "source-hash-change",
]


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


SCENARIOS: tuple[Scenario, ...] = (
    "token-order",
    "protect-before-casefold",
    "mp-domain-case",
    "protected-decimal",
    "relation-boundary",
    "range-boundary",
    "sign-range-precedence",
    "pure-korean-unsupported",
    "zero",
    "negative",
    "broken-range",
    "si-case",
    "formula-error",
    "external-link",
    "ambiguous-number",
    "source-hash-change",
)


def _behavior(
    condition: bool,
    assertion_class: str,
    message: str,
) -> FailureObservation:
    assert condition, message
    return FailureObservation(assertion_class, message)


def _capture[ErrorT: Exception](
    error_type: type[ErrorT],
    call: Callable[[], ParsedSpecs | None],
) -> FailureObservation:
    try:
        _ = call()
    except error_type as error:
        return FailureObservation(type(error).__name__, str(error))
    pytest.fail(f"scenario did not fail with {error_type.__name__}")


def _workbook(path: Path, formula: str) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet["A1"] = formula
    workbook.save(path)


def _observe_behavior(scenario: BehaviorScenario) -> FailureObservation:
    match scenario:
        case "token-order":
            tokens = normalize_text("앞 8MP 뒤").tokens
            observation = _behavior(
                tokens == ("앞", "8MP", "뒤"),
                "TokenOrderError",
                "token source order",
            )
        case "protect-before-casefold":
            tokens = normalize_text("A 8MP B").tokens
            observation = _behavior(
                tokens == ("a", "8MP", "b"),
                "ProtectedTokenError",
                "protected token before casefold",
            )
        case "mp-domain-case":
            value = parse_specs("8mP").semantics[0].value
            observation = _behavior(
                value == 8_000_000,
                "UnitAliasError",
                "MP megapixel case-insensitive",
            )
        case "protected-decimal":
            tokens = normalize_text("카메라 1,234.5kHz").tokens
            observation = _behavior(
                "1,234.5kHz" in tokens,
                "ProtectedTokenError",
                "decimal quantity protected",
            )
        case "relation-boundary":
            relation = parse_specs("30fps 이상").semantics[0].relation
            observation = _behavior(
                relation == "gte",
                "RelationParseError",
                "relation boundary",
            )
        case "range-boundary":
            semantic = parse_specs("10-20Hz").semantics[0]
            observation = _behavior(
                (semantic.lower, semantic.upper) == (10, 20),
                "RangeParseError",
                "range boundary",
            )
        case "sign-range-precedence":
            _ = _capture(InvalidQuantityError, lambda: parse_specs("-10Hz"))
            upper = parse_specs("10-20Hz").semantics[0].upper
            observation = _behavior(
                upper == 20,
                "SignRangePrecedenceError",
                "sign range precedence",
            )
        case _:
            assert_never(scenario)
    return observation


def _observe_parser_error(scenario: ParserErrorScenario) -> FailureObservation:
    match scenario:
        case "pure-korean-unsupported":
            observation = _capture(
                UnsupportedNumberError,
                lambda: parse_specs("팔백만화소"),
            )
        case "zero":
            observation = _capture(InvalidQuantityError, lambda: parse_specs("0Hz"))
        case "negative":
            observation = _capture(InvalidQuantityError, lambda: parse_specs("-1Hz"))
        case "broken-range":
            observation = _capture(RangeParseError, lambda: parse_specs("10-Hz"))
        case "si-case":
            observation = _capture(UnitAliasError, lambda: parse_specs("3KHZ"))
        case "ambiguous-number":
            observation = _capture(
                AmbiguousNumberError,
                lambda: parse_specs("1,2,3Hz"),
            )
        case _:
            assert_never(scenario)
    return observation


def _observe_workbook_error(
    scenario: WorkbookErrorScenario,
    temp_root: Path,
) -> FailureObservation:
    match scenario:
        case "formula-error":
            path = temp_root / "formula.xlsx"
            _workbook(path, "=1+1")
            observation = _capture(
                WorkbookFormulaError,
                lambda: inspect_workbook(path),
            )
        case "external-link":
            path = temp_root / "external.xlsx"
            _workbook(path, "='[other.xlsx]Sheet1'!A1")
            observation = _capture(
                WorkbookExternalLinkError,
                lambda: inspect_workbook(path),
            )
        case "source-hash-change":
            path = temp_root / "source.xlsx"
            _ = path.write_bytes(b"changed")
            observation = _capture(
                WorkbookSourceHashError,
                lambda: verify_source_hash(path, "0" * 64),
            )
        case _:
            assert_never(scenario)
    return observation


def observe_failure(scenario: Scenario, temp_root: Path) -> FailureObservation:
    match scenario:
        case (
            "token-order"
            | "protect-before-casefold"
            | "mp-domain-case"
            | "protected-decimal"
            | "relation-boundary"
            | "range-boundary"
            | "sign-range-precedence"
        ):
            return _observe_behavior(scenario)
        case (
            "pure-korean-unsupported"
            | "zero"
            | "negative"
            | "broken-range"
            | "si-case"
            | "ambiguous-number"
        ):
            return _observe_parser_error(scenario)
        case "formula-error" | "external-link" | "source-hash-change":
            return _observe_workbook_error(scenario, temp_root)
        case _:
            assert_never(scenario)
