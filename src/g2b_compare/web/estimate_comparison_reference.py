"""Load and match workbook-grounded comparison references."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .estimate_models import ComparisonView

if TYPE_CHECKING:
    from g2b_compare.services import EstimateLine


class ComparisonReferenceSnapshot(BaseModel):
    """One A, B, or C snapshot copied from a source workbook."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    slot: Literal["A", "B", "C"]
    product_id: str
    company: str
    spec: str
    price_won: int


class ComparisonReferenceLine(BaseModel):
    """One source row and its ordered comparison snapshots."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    source_row: int = Field(alias="row")
    quantity: str
    spec: str
    comparisons: tuple[
        ComparisonReferenceSnapshot,
        ComparisonReferenceSnapshot,
        ComparisonReferenceSnapshot,
    ]

    @model_validator(mode="after")
    def validate_slots(self) -> Self:
        """Require the workbook's stable A, B, C slot order."""
        if tuple(item.slot for item in self.comparisons) != ("A", "B", "C"):
            msg = "comparison reference slots must be ordered A, B, C"
            raise ValueError(msg)
        return self


class ComparisonReferenceDocument(BaseModel):
    """One workbook worksheet and its ordered source rows."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    workbook: str
    worksheet: Literal["단가조사"]
    rows: tuple[ComparisonReferenceLine, ...]


class _ComparisonReferenceCatalog(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["g2b-comparison-reference-v1"] = Field(alias="schema")
    documents: tuple[ComparisonReferenceDocument, ...]


@lru_cache(maxsize=1)
def _catalog() -> _ComparisonReferenceCatalog:
    path = Path(__file__).with_name("estimate_comparison_reference.json")
    return _ComparisonReferenceCatalog.model_validate_json(path.read_bytes())


def comparison_reference_documents() -> tuple[
    ComparisonReferenceDocument,
    ...,
]:
    """Return the immutable workbook comparison reference catalog."""
    return _catalog().documents


def reference_document_comparisons(
    lines: tuple[EstimateLine, ...],
) -> tuple[tuple[ComparisonView, ...], ...] | None:
    """Return exact comparisons when lines match one reference document."""
    for document in comparison_reference_documents():
        remaining = list(document.rows)
        matched: list[ComparisonReferenceLine] = []
        for line in lines:
            candidates = [
                reference for reference in remaining if _line_matches(reference, line)
            ]
            if len(candidates) != 1:
                break
            reference = candidates[0]
            matched.append(reference)
            remaining.remove(reference)
        if len(matched) != len(lines):
            continue
        return tuple(
            tuple(
                ComparisonView(
                    snapshot.slot,
                    snapshot.product_id,
                    line.relation_id if snapshot.slot == "A" else None,
                    snapshot.company,
                    snapshot.spec,
                    snapshot.price_won,
                )
                for snapshot in reference.comparisons
            )
            for reference, line in zip(matched, lines, strict=True)
        )
    return None


def _line_matches(
    reference: ComparisonReferenceLine,
    line: EstimateLine,
) -> bool:
    selected = reference.comparisons[0]
    return line.product_id == selected.product_id and line.quantity == Decimal(
        reference.quantity
    )
