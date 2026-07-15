"""Define typed errors and immutable values produced by spec parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from .text import NormalizedText


class RangeParseError(ValueError):
    """Report a syntactically incomplete or non-increasing range."""

    raw: str

    def __init__(self, raw: str) -> None:
        """Build an error for one invalid range."""
        super().__init__(f"broken range rejected: {raw}")
        self.raw = raw


class RelationParseError(ValueError):
    """Report a quantity relation that does not end on a token boundary."""

    raw: str

    def __init__(self, raw: str) -> None:
        """Build an error for one invalid relation."""
        super().__init__(f"relation boundary rejected: {raw}")
        self.raw = raw


class UnitDimensionError(ValueError):
    """Report incompatible units inside one structured specification."""

    left: str
    right: str

    def __init__(self, left: str, right: str) -> None:
        """Build an error for two incompatible unit dimensions."""
        super().__init__(f"unit dimension mismatch: {left} and {right}")
        self.left = left
        self.right = right


class SpecKind(StrEnum):
    """Identify the supported protected specification shapes."""

    SCALAR = "scalar"
    RELATION = "relation"
    RANGE = "range"
    DIMENSION = "dimension"


class Relation(StrEnum):
    """Represent exact and directed comparison semantics."""

    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    GT = "gt"
    LT = "lt"
    RANGE = "range"


@dataclass(frozen=True, slots=True)
class SpecSpan:
    """Preserve the source bytes and normalized form of one parsed span."""

    start_byte: int
    end_byte: int
    raw: str
    normalized: str
    kind: SpecKind


@dataclass(frozen=True, slots=True)
class SpecSemantic:
    """Hold one canonical scalar, relation, range, or dimension observation."""

    attribute_key: str
    relation: Relation
    value: Decimal | None
    lower: Decimal | None
    upper: Decimal | None
    canonical_unit: str
    dimension: str
    source_span: SpecSpan


@dataclass(frozen=True, slots=True)
class ParsedSpecs:
    """Keep raw and normalized text beside ordered spans and semantics."""

    raw: str
    normalized: NormalizedText
    spans: tuple[SpecSpan, ...]
    semantics: tuple[SpecSemantic, ...]
