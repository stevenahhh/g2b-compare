from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.ranking.formula import FormulaInput, score_formula


class CandidateEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    option: bool
    price: bool


class HandInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    lexical: str
    fuzzy: str
    structured: str | None
    price: str | None
    price_distance: str | None
    anchor_option: bool
    anchor_specs: int
    matched_specs: int
    anchor_price: bool


class HandExpected(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    lexical: str
    fuzzy: str
    structured: str | None
    price: str | None
    denominator: str
    score_raw: str | None
    score: str | None
    coverage: str | None
    price_distance: str | None


class HandCase(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: str
    input: HandInput
    candidate_evidence: CandidateEvidence
    expected: HandExpected


class HandFixture(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    ranking_version: str
    cases: tuple[HandCase, ...]


def test_hand_calculated_fixture_is_canonical_and_exact() -> None:
    path = Path("tests/fixtures/ranking/hand-calculated-v1.json")
    payload = path.read_bytes()
    fixture = TypeAdapter(HandFixture).validate_json(payload)

    assert hashlib.sha256(payload).hexdigest() == (
        "6f7833bcdccf3a05dfc71c82fc0d75f6fc26691eebe04b0ac607f22df5cd7c3c"
    )
    assert fixture.ranking_version == "v1"
    for case in fixture.cases:
        _assert_case(case)


def _assert_case(case: HandCase) -> None:
    source = case.input
    result = score_formula(
        FormulaInput(
            lexical=Decimal(source.lexical),
            fuzzy=Decimal(source.fuzzy),
            structured=_decimal(source.structured),
            price=_decimal(source.price),
            price_distance=_decimal(source.price_distance),
            anchor_option_present=source.anchor_option,
            candidate_option_present=case.candidate_evidence.option,
            anchor_spec_count=source.anchor_specs,
            matched_anchor_count=source.matched_specs,
            anchor_price_active=source.anchor_price,
            candidate_price_comparable=case.candidate_evidence.price,
        )
    )
    expected = case.expected
    assert str(result.lexical) == expected.lexical
    assert str(result.fuzzy) == expected.fuzzy
    assert _string(result.structured) == expected.structured
    assert _string(result.price) == expected.price
    assert str(result.denominator) == expected.denominator
    assert _string(result.score_raw) == expected.score_raw
    assert _string(result.score) == expected.score
    assert _string(result.coverage) == expected.coverage
    assert _string(result.price_distance) == expected.price_distance


def _string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
