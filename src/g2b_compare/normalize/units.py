"""Resolve units from the versioned normalization data catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Protocol, TypedDict


class UnitAliasError(ValueError):
    """Report an unrecognized alias or a known SI alias with wrong case."""

    alias: str
    si_case: bool

    def __init__(self, alias: str, *, si_case: bool = False) -> None:
        """Build an error for one unknown or wrongly cased alias."""
        message = (
            f"SI unit case-sensitive: {alias}"
            if si_case
            else f"unrecognized unit: {alias}"
        )
        super().__init__(message)
        self.alias = alias
        self.si_case = si_case


class _NormalizationDataError(RuntimeError):
    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(f"normalization data invalid: {detail}")
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Unit:
    """Describe one canonical unit, dimension, attribute, and scale factor."""

    canonical: str
    dimension: str
    attribute_key: str
    factor: Decimal = Decimal(1)


class _UnitRecord(TypedDict):
    alias: str
    case_sensitive: bool
    canonical: str
    dimension: str
    attribute: str
    factor: str


class _UnitData(TypedDict):
    version: str
    units: list[_UnitRecord]


class _AttributeData(TypedDict):
    version: str
    dimension_attributes: list[str]
    scalar_attributes: list[str]


class _UnitDataLoader(Protocol):
    def __call__(self, s: str | bytes | bytearray) -> _UnitData: ...


class _AttributeDataLoader(Protocol):
    def __call__(self, s: str | bytes | bytearray) -> _AttributeData: ...


def _load_unit_data(loader: _UnitDataLoader, path: Path) -> _UnitData:
    return loader(path.read_bytes())


def _load_attribute_data(
    loader: _AttributeDataLoader,
    path: Path,
) -> _AttributeData:
    return loader(path.read_bytes())


_DATA_DIRECTORY: Final = Path(__file__).with_name("data")
_UNIT_DATA: Final = _load_unit_data(
    json.loads,
    _DATA_DIRECTORY / "units-v2.json",
)
_ATTRIBUTE_DATA: Final = _load_attribute_data(
    json.loads,
    _DATA_DIRECTORY / "attributes-v2.json",
)
NORMALIZATION_VERSION: Final = _UNIT_DATA["version"]

if _ATTRIBUTE_DATA["version"] != NORMALIZATION_VERSION:
    detail = "unit and attribute versions differ"
    raise _NormalizationDataError(detail)

_ATTRIBUTE_KEYS: Final = frozenset(
    (*_ATTRIBUTE_DATA["dimension_attributes"], *_ATTRIBUTE_DATA["scalar_attributes"]),
)
_UNKNOWN_ATTRIBUTES: Final = tuple(
    sorted(
        record["attribute"]
        for record in _UNIT_DATA["units"]
        if record["attribute"] not in _ATTRIBUTE_KEYS
    ),
)
if _UNKNOWN_ATTRIBUTES:
    detail = f"unknown unit attributes: {', '.join(_UNKNOWN_ATTRIBUTES)}"
    raise _NormalizationDataError(detail)

_UNITS_BY_ALIAS: Final = {
    record["alias"]: Unit(
        record["canonical"],
        record["dimension"],
        record["attribute"],
        Decimal(record["factor"]),
    )
    for record in _UNIT_DATA["units"]
}
_EXACT_ALIASES: Final = frozenset(
    record["alias"] for record in _UNIT_DATA["units"] if record["case_sensitive"]
)
_INSENSITIVE_ALIASES: Final = {
    record["alias"].casefold(): record["alias"]
    for record in _UNIT_DATA["units"]
    if not record["case_sensitive"]
}
_SI_CASEFOLDED: Final = frozenset(
    alias.casefold() for alias in _EXACT_ALIASES if alias.isascii() and alias.isalpha()
)
ALIASES: Final = tuple(
    sorted(_UNITS_BY_ALIAS, key=lambda item: (-len(item), item)),
)


def resolve_unit(alias: str) -> Unit:
    """Resolve a case-insensitive domain alias or an exact SI/domain alias."""
    if alias in _EXACT_ALIASES:
        return _UNITS_BY_ALIAS[alias]
    canonical_alias = _INSENSITIVE_ALIASES.get(alias.casefold())
    if canonical_alias is not None:
        return _UNITS_BY_ALIAS[canonical_alias]
    if alias.casefold() in _SI_CASEFOLDED:
        raise UnitAliasError(alias, si_case=True)
    raise UnitAliasError(alias)


def is_wrong_case_si_alias(alias: str) -> bool:
    """Return whether an alphabetic token is a known SI alias in wrong case."""
    return alias not in _EXACT_ALIASES and alias.casefold() in _SI_CASEFOLDED
