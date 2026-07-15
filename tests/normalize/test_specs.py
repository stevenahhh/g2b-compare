"""Given Korean specs, verify typed canonical observations."""

from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict

from g2b_compare.normalize import (
    NORMALIZATION_VERSION,
    TOKENIZER_VERSION,
    AmbiguousNumberError,
    InvalidQuantityError,
    RangeParseError,
    UnitAliasError,
    UnitDimensionError,
    UnsupportedNumberError,
    parse_specs,
    resolve_unit,
)
from g2b_compare.normalize.units import ALIASES


class _WorkbookSmokeFixture(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    cases: tuple[str, ...]
    schema_version: str


class _UnitRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    alias: str


class _UnitData(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    version: str
    units: tuple[_UnitRecord, ...]


@pytest.mark.parametrize(
    ("raw", "value", "unit", "attribute"),
    [
        ("800만화소", Decimal(8000000), "pixel", "resolution"),
        ("8MP", Decimal(8000000), "pixel", "resolution"),
        ("4배줌", Decimal(4), "times", "zoom"),
        ("1,234.5kHz", Decimal(1234500), "Hz", "frequency"),
    ],
)
def test_scalar_quantities(raw: str, value: Decimal, unit: str, attribute: str) -> None:
    parsed = parse_specs(raw)
    semantic = parsed.semantics[0]
    assert parsed.raw == raw
    assert semantic.value == value
    assert semantic.canonical_unit == unit
    assert semantic.attribute_key == attribute


def test_dimension_has_one_span_and_three_semantics() -> None:
    parsed = parse_specs("해상도 3840\u00d72160")
    assert len(parsed.spans) == 1
    assert parsed.spans[0].raw == "3840\u00d72160"
    assert [item.value for item in parsed.semantics] == [
        Decimal(3840),
        Decimal(2160),
        Decimal(8294400),
    ]
    assert parsed.semantics[-1].canonical_unit == "pixel"


def test_relations_and_ranges() -> None:
    assert parse_specs("30fps 이하").semantics[0].relation == "lte"
    ranged = parse_specs("10~20Hz").semantics[0]
    assert (ranged.lower, ranged.upper, ranged.value) == (
        Decimal(10),
        Decimal(20),
        None,
    )


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("팔백만화소", UnsupportedNumberError),
        ("0Hz", InvalidQuantityError),
        ("-2Hz", InvalidQuantityError),
        ("2-Hz", RangeParseError),
        ("1,2,3Hz", AmbiguousNumberError),
        ("3KHZ", UnitAliasError),
    ],
)
def test_invalid_quantity_contract(raw: str, error: type[ValueError]) -> None:
    with pytest.raises(error):
        _ = parse_specs(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "10m/s",
        "8MP/s",
        "550\u00d7600\u00d7550mm",
        "30fps>=x",
        "30fps 이상급",
        "10-20Hz급",
    ],
)
def test_unsupported_compounds_never_emit_partial_semantics(raw: str) -> None:
    parsed = parse_specs(raw)
    assert parsed.raw == raw
    assert parsed.normalized.protected == ()
    assert parsed.spans == ()
    assert parsed.semantics == ()


_RANGE_UNITS = ("mm", "Hz", "V", "W", "GB", "FPS", "MP")


@given(st.sampled_from(_RANGE_UNITS), st.sampled_from(_RANGE_UNITS))
@settings(derandomize=True, max_examples=49)
def test_range_units_from_different_dimensions_fail_closed(
    left_alias: str,
    right_alias: str,
) -> None:
    _ = assume(
        resolve_unit(left_alias).dimension != resolve_unit(right_alias).dimension,
    )
    with pytest.raises(UnitDimensionError):
        _ = parse_specs(f"1{left_alias}-2{right_alias}")


def test_workbook_smoke_fixture_is_consumed_by_parser() -> None:
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "normalization"
        / "workbook-smoke-v1.json"
    )
    fixture = _WorkbookSmokeFixture.model_validate_json(fixture_path.read_bytes())
    assert fixture.schema_version == "normalization-workbook-smoke-v1"
    for case in fixture.cases:
        raw = case.split(":", maxsplit=3)[-1]
        assert parse_specs(raw).raw == raw


def test_version_and_unit_data_seams_are_machine_readable() -> None:
    data_path = (
        Path(__file__).parents[2]
        / "src"
        / "g2b_compare"
        / "normalize"
        / "data"
        / "units-v1.json"
    )
    data = _UnitData.model_validate_json(data_path.read_bytes())
    expected_aliases = tuple(
        sorted(
            (*(record.alias for record in data.units),),
            key=lambda item: (-len(item), item),
        ),
    )
    assert NORMALIZATION_VERSION == data.version == "v1"
    assert TOKENIZER_VERSION == "v1"
    assert expected_aliases == ALIASES
