"""Parse protected v1 quantities into typed canonical specifications."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .numbers import (
    NUMBER_WITH_MAN,
    InvalidQuantityError,
    UnsupportedNumberError,
    parse_number,
    require_positive,
)
from .spec_types import (
    ParsedSpecs,
    RangeParseError,
    Relation,
    RelationParseError,
    SpecKind,
    SpecSemantic,
    SpecSpan,
    UnitDimensionError,
)
from .text import ProtectedSpan, normalize_text
from .tokens import UNIT_PATTERN
from .units import Unit, is_wrong_case_si_alias, resolve_unit

if TYPE_CHECKING:
    from decimal import Decimal


@dataclass(frozen=True, slots=True)
class _SemanticValues:
    relation: Relation = Relation.EQ
    value: Decimal | None = None
    lower: Decimal | None = None
    upper: Decimal | None = None


_DIMENSION_RE: Final = re.compile(
    "".join(
        (
            rf"^(?P<left>{NUMBER_WITH_MAN})\s*[xX\u00d7]\s*",
            rf"(?P<right>{NUMBER_WITH_MAN})(?:\s*(?P<unit>{UNIT_PATTERN}))?$",
        ),
    ),
)
_RANGE_RE: Final = re.compile(
    "".join(
        (
            rf"^(?P<left>{NUMBER_WITH_MAN})(?P<left_unit>{UNIT_PATTERN})?\s*[~-]\s*",
            rf"(?P<right>{NUMBER_WITH_MAN})(?P<right_unit>{UNIT_PATTERN})?$",
        ),
    ),
)
_RELATION_RE: Final = re.compile(
    "".join(
        (
            rf"^(?P<number>{NUMBER_WITH_MAN})(?P<unit>{UNIT_PATTERN})\s*",
            r"(?P<relation>이상|이하|초과|미만|>=|<=|>|<)$",
        ),
    ),
)
_SCALAR_RE: Final = re.compile(
    rf"^(?P<number>{NUMBER_WITH_MAN})(?P<unit>{UNIT_PATTERN})$",
)
_NEGATIVE_RE: Final = re.compile(
    "".join(
        (
            r"(?:^|[\(\[\{,:=<>~]|이상|이하|초과|미만)\s*-\s*",
            rf"(?P<number>{NUMBER_WITH_MAN})(?P<unit>{UNIT_PATTERN})",
        ),
    ),
)
_BROKEN_RANGE_RE: Final = re.compile(
    rf"{NUMBER_WITH_MAN}(?:{UNIT_PATTERN})?\s*[~-]\s*{UNIT_PATTERN}",
)
_KOREAN_NUMBER_RE: Final = re.compile(
    rf"(?<![0-9])(?P<number>[영공일이삼사오육칠팔구십백천만억]+)(?={UNIT_PATTERN})",
)
_LATIN_QUANTITY_RE: Final = re.compile(
    rf"{NUMBER_WITH_MAN}(?P<unit>[A-Za-z]+)",
)
_COMMA_QUANTITY_RE: Final = re.compile(
    rf"(?P<number>\d[\d,]*(?:\.\d+)?)(?={UNIT_PATTERN})",
)
_RELATIONS: Final = {
    "이상": Relation.GTE,
    ">=": Relation.GTE,
    "이하": Relation.LTE,
    "<=": Relation.LTE,
    "초과": Relation.GT,
    ">": Relation.GT,
    "미만": Relation.LT,
    "<": Relation.LT,
}


def _canonical_value(number: str, unit: Unit, raw: str) -> Decimal:
    return require_positive(parse_number(number), raw=raw) * unit.factor


def _span(source: ProtectedSpan, kind: SpecKind) -> SpecSpan:
    return SpecSpan(
        source.start_byte,
        source.end_byte,
        source.raw,
        source.normalized,
        kind,
    )


def _semantic(
    span: SpecSpan,
    unit: Unit,
    values: _SemanticValues,
) -> SpecSemantic:
    return SpecSemantic(
        unit.attribute_key,
        values.relation,
        values.value,
        values.lower,
        values.upper,
        unit.canonical,
        unit.dimension,
        span,
    )


def _parse_dimension(
    source: ProtectedSpan,
    match: re.Match[str],
) -> tuple[SpecSpan, tuple[SpecSemantic, ...]]:
    span = _span(source, SpecKind.DIMENSION)
    alias = match.group("unit") or "PX"
    unit = resolve_unit(alias)
    if unit.dimension not in {"resolution", "length"}:
        raise UnitDimensionError(alias, "dimension")
    left = _canonical_value(match.group("left"), unit, source.raw)
    right = _canonical_value(match.group("right"), unit, source.raw)
    width_unit = Unit(unit.canonical, unit.dimension, "width")
    height_unit = Unit(unit.canonical, unit.dimension, "height")
    observations = (
        _semantic(span, width_unit, _SemanticValues(value=left)),
        _semantic(span, height_unit, _SemanticValues(value=right)),
    )
    if unit.dimension == "resolution":
        total_unit = Unit("pixel", "resolution", "total-pixel")
        total = _semantic(span, total_unit, _SemanticValues(value=left * right))
        return span, (*observations, total)
    return span, observations


def _parse_range(
    source: ProtectedSpan,
    match: re.Match[str],
) -> tuple[SpecSpan, tuple[SpecSemantic, ...]]:
    left_alias = match.group("left_unit") or match.group("right_unit")
    right_alias = match.group("right_unit") or match.group("left_unit")
    if left_alias is None or right_alias is None:
        raise RangeParseError(source.raw)
    left_unit = resolve_unit(left_alias)
    right_unit = resolve_unit(right_alias)
    if left_unit.dimension != right_unit.dimension:
        raise UnitDimensionError(left_alias, right_alias)
    if left_unit.canonical != right_unit.canonical:
        raise UnitDimensionError(left_alias, right_alias)
    lower = _canonical_value(match.group("left"), left_unit, source.raw)
    upper = _canonical_value(match.group("right"), right_unit, source.raw)
    if lower >= upper:
        raise RangeParseError(source.raw)
    span = _span(source, SpecKind.RANGE)
    return span, (
        _semantic(
            span,
            right_unit,
            _SemanticValues(
                relation=Relation.RANGE,
                lower=lower,
                upper=upper,
            ),
        ),
    )


def _parse_relation(
    source: ProtectedSpan,
    match: re.Match[str],
) -> tuple[SpecSpan, tuple[SpecSemantic, ...]]:
    unit = resolve_unit(match.group("unit"))
    value = _canonical_value(match.group("number"), unit, source.raw)
    relation = _RELATIONS[match.group("relation")]
    span = _span(source, SpecKind.RELATION)
    values = _SemanticValues(relation=relation, value=value)
    return span, (_semantic(span, unit, values),)


def _parse_scalar(
    source: ProtectedSpan,
    match: re.Match[str],
) -> tuple[SpecSpan, tuple[SpecSemantic, ...]]:
    unit = resolve_unit(match.group("unit"))
    value = _canonical_value(match.group("number"), unit, source.raw)
    span = _span(source, SpecKind.SCALAR)
    return span, (_semantic(span, unit, _SemanticValues(value=value)),)


def _parse_protected(
    source: ProtectedSpan,
) -> tuple[SpecSpan, tuple[SpecSemantic, ...]]:
    dimension = _DIMENSION_RE.fullmatch(source.normalized)
    if dimension is not None:
        return _parse_dimension(source, dimension)
    range_match = _RANGE_RE.fullmatch(source.normalized)
    if range_match is not None:
        return _parse_range(source, range_match)
    relation = _RELATION_RE.fullmatch(source.normalized)
    if relation is not None:
        return _parse_relation(source, relation)
    scalar = _SCALAR_RE.fullmatch(source.normalized)
    if scalar is not None:
        return _parse_scalar(source, scalar)
    raise RelationParseError(source.raw)


def _reject_invalid(raw: str) -> None:
    for candidate in _COMMA_QUANTITY_RE.finditer(raw):
        number = candidate.group("number")
        if "," in number:
            _ = parse_number(number)
    negative = _NEGATIVE_RE.search(raw)
    if negative is not None:
        value = parse_number(negative.group("number"))
        raise InvalidQuantityError(negative.group(0), -value, negative=True)
    korean_number = _KOREAN_NUMBER_RE.search(raw)
    if korean_number is not None:
        raise UnsupportedNumberError(korean_number.group("number"), pure_korean=True)
    for candidate in _LATIN_QUANTITY_RE.finditer(raw):
        alias = candidate.group("unit")
        if is_wrong_case_si_alias(alias):
            _ = resolve_unit(alias)
    broken_range = _BROKEN_RANGE_RE.search(raw)
    if broken_range is not None:
        raise RangeParseError(broken_range.group(0))


def parse_specs(raw: str) -> ParsedSpecs:
    """Parse every supported quantity span in deterministic source order."""
    nfkc = unicodedata.normalize("NFKC", raw)
    _reject_invalid(nfkc)
    normalized = normalize_text(raw)
    spans: list[SpecSpan] = []
    semantics: list[SpecSemantic] = []
    for protected in normalized.protected:
        span, observations = _parse_protected(protected)
        spans.append(span)
        semantics.extend(observations)
    return ParsedSpecs(raw, normalized, tuple(spans), tuple(semantics))
