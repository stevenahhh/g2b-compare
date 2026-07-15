"""Typed workbook fixture contracts shared by extraction and publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, override

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True, slots=True)
class FixtureError(Exception):
    """Fail-closed fixture extraction error."""

    detail: str

    @override
    def __str__(self) -> str:
        """Return the actionable failure detail."""
        return self.detail


class CellExpectation(BaseModel):
    """One exact workbook cell/value contract."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    coordinate: str
    value: str


class RelationGrammar(BaseModel):
    """Machine-readable Todo 7 relation grammar pinned by Todo 4."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str
    source_sha256: str
    sheet: str
    headers: tuple[CellExpectation, ...]
    parent: CellExpectation
    child_cells: tuple[str, ...]
    unbound_option_cells: tuple[str, ...]
    product_id_pattern: str
    curated_relationship_count: int
    unbound_option_count: int


RELATION_GRAMMAR: Final = RelationGrammar(
    schema_version="workbook-relations-v1",
    source_sha256=("445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db"),
    sheet="자재내역서",
    headers=(
        CellExpectation(coordinate="B8", value="1-1. 본품"),
        CellExpectation(coordinate="B10", value="1-2. 우수제품 옵션품목"),
        CellExpectation(coordinate="B26", value="2-1. 옵션품목"),
    ),
    parent=CellExpectation(coordinate="N9", value="24684676"),
    child_cells=tuple(f"N{row}" for row in range(11, 23)),
    unbound_option_cells=tuple(f"N{row}" for row in range(27, 30)),
    product_id_pattern=r"\A[0-9]{8}\Z",
    curated_relationship_count=12,
    unbound_option_count=3,
)


class SheetFacts(BaseModel):
    """Stable facts for one source worksheet."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str
    dimension: str
    rows: int
    columns: int
    formula_cells: int
    merged_ranges: int


class WorkbookTotals(BaseModel):
    """Stable aggregate facts for one source workbook."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    formula_cells: int
    merged_ranges: int
    external_links: int
    curated_relationships: int
    unbound_options: int


class WorkbookFacts(BaseModel):
    """Stable workbook identity and sheet facts."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    filename: str
    sha256: str
    sheets: tuple[SheetFacts, ...]
    totals: WorkbookTotals


class Manifest(BaseModel):
    """Deterministic source workbook manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str
    relation_grammar: RelationGrammar
    workbooks: tuple[WorkbookFacts, ...]


class SmokeFixture(BaseModel):
    """Deterministic real-workbook smoke cases."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str
    cases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FixtureBundle:
    """All outputs produced from one immutable source set."""

    manifest: Manifest
    normalization: SmokeFixture
    ranking: SmokeFixture
