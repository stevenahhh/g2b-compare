"""Typed estimate export inputs, manifest, and errors."""

from dataclasses import dataclass
from typing import ClassVar, Literal, final, override

from pydantic import BaseModel, ConfigDict


class ImageSlot(BaseModel):
    """One preserved drawing slot backed by a unique media part."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    line_index: int
    comparison_slot: Literal["A", "B", "C"]
    media_path: str


class TemplateManifest(BaseModel):
    """Validated fixed-template coordinates."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    template_sha256: str
    sheet_names: list[str]
    title_cell: dict[str, str]
    quantity_rows: dict[str, str | int]
    price_rows: dict[str, str | int]
    image_slots: list[ImageSlot]


@dataclass(frozen=True, slots=True)
class ComparisonSnapshot:
    """One immutable A/B/C workbook comparison value set."""

    slot: Literal["A", "B", "C"]
    product_id: str
    company: str
    spec: str
    price_won: int


@final
class EstimateExportError(Exception):
    """The draft cannot be safely mapped to the fixed workbook."""

    detail: str

    def __init__(self, detail: str) -> None:
        """Initialize one actionable export rejection."""
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail
