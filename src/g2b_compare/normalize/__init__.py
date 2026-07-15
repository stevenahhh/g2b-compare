"""Expose the versioned normalization and specification parser API."""

from .numbers import (
    AmbiguousNumberError,
    InvalidQuantityError,
    NumberParseError,
    UnsupportedNumberError,
    parse_number,
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
from .specs import parse_specs
from .text import NormalizedText, ProtectedSpan, normalize_text
from .tokens import TOKENIZER_VERSION
from .units import NORMALIZATION_VERSION, Unit, UnitAliasError, resolve_unit
from .workbooks import (
    WorkbookExternalLinkError,
    WorkbookFormulaError,
    WorkbookSourceHashError,
    inspect_workbook,
    verify_source_hash,
)

__all__ = (
    "NORMALIZATION_VERSION",
    "TOKENIZER_VERSION",
    "AmbiguousNumberError",
    "InvalidQuantityError",
    "NormalizedText",
    "NumberParseError",
    "ParsedSpecs",
    "ProtectedSpan",
    "RangeParseError",
    "Relation",
    "RelationParseError",
    "SpecKind",
    "SpecSemantic",
    "SpecSpan",
    "Unit",
    "UnitAliasError",
    "UnitDimensionError",
    "UnsupportedNumberError",
    "WorkbookExternalLinkError",
    "WorkbookFormulaError",
    "WorkbookSourceHashError",
    "inspect_workbook",
    "normalize_text",
    "parse_number",
    "parse_specs",
    "resolve_unit",
    "verify_source_hash",
)
