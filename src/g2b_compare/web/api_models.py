"""JSON response models for the read-only catalog API."""

from __future__ import annotations

from decimal import Decimal  # noqa: TC003 - Pydantic resolves this field at runtime.
from typing import Annotated, ClassVar, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


class DataStatusResponse(BaseModel):
    """Persisted priority counts with the read-only readiness state."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    company_count: int
    option_row_count: int
    unique_option_count: int
    product_count: int
    relation_count: int
    pending_api_target_count: int
    pending_site_product_count: int
    ready: bool
    readiness: Literal["ready", "empty"]


class CatalogAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    unit: str = ""


class CatalogProductResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    name: str
    spec: str
    unit: str
    price_won: int
    company_name: str
    contract_method: str
    delivery_condition: str
    delivery_days: str
    contract_end_date: str
    detail_url: str
    g2b_url: str
    image_url: str
    attributes: list[CatalogAttributeResponse]


class CatalogOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_product_id: str
    parent_name: str = ""
    relation_id: str
    relation_kind: Literal["additional", "component"]
    product_id: str
    name: str
    spec: str
    unit: str
    price_won: int
    company_name: str
    detail_url: str
    g2b_url: str
    image_url: str
    attributes: list[CatalogAttributeResponse] = Field(default_factory=list)


class CatalogPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CatalogProductResponse | CatalogOptionResponse]
    page: int
    page_count: int
    total_count: int


ClientHexId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{32}$")]
ProductId = Annotated[str, Field(pattern=r"^\d{8}$")]
OptionalText = Annotated[str, Field(min_length=1)] | None
LINE_RELATION_ERROR: Final = "estimate_line_relation"
LINE_RELATION_MESSAGE: Final = "line kind and relation context do not match"
LINE_ID_DUPLICATE_ERROR: Final = "estimate_line_id_duplicate"
LINE_ID_DUPLICATE_MESSAGE: Final = "line IDs must be unique within an estimate"
RELATION_ID_DUPLICATE_ERROR: Final = "estimate_relation_id_duplicate"
RELATION_ID_DUPLICATE_MESSAGE: Final = "relation IDs must be unique within an estimate"


class EstimateLineRequest(BaseModel):
    """One complete cached line snapshot supplied by the browser."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: ClientHexId
    line_kind: Literal["main", "option"]
    product_id: ProductId
    parent_product_id: ProductId | None = None
    relation_id: OptionalText = None
    offer_operation: OptionalText = None
    offer_key: OptionalText = None
    item_name_snapshot: str
    spec_snapshot: str
    company_snapshot: str
    unit_snapshot: str
    unit_price_won_snapshot: int = Field(ge=0)
    quantity: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def require_relation_context(self) -> EstimateLineRequest:
        """Require parent and relation identity only for option lines."""
        match self.line_kind:
            case "main":
                valid = self.parent_product_id is None and self.relation_id is None
            case "option":
                valid = (
                    self.parent_product_id is not None and self.relation_id is not None
                )
            case unreachable:
                assert_never(unreachable)
        if not valid:
            raise PydanticCustomError(
                LINE_RELATION_ERROR,
                LINE_RELATION_MESSAGE,
            )
        return self


class EstimateDocumentRequest(BaseModel):
    """One latest non-empty estimate state used for idempotent replay."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    lines: list[EstimateLineRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_line_and_relation_ids(self) -> EstimateDocumentRequest:
        """Reject ambiguous full-document identities before opening a transaction."""
        line_ids = tuple(line.id for line in self.lines)
        relation_ids = tuple(
            line.relation_id for line in self.lines if line.relation_id is not None
        )
        if len(set(line_ids)) != len(line_ids):
            raise PydanticCustomError(
                LINE_ID_DUPLICATE_ERROR,
                LINE_ID_DUPLICATE_MESSAGE,
            )
        if len(set(relation_ids)) != len(relation_ids):
            raise PydanticCustomError(
                RELATION_ID_DUPLICATE_ERROR,
                RELATION_ID_DUPLICATE_MESSAGE,
            )
        return self


class EstimateComparisonResponse(BaseModel):
    """One pinned A/B/C comparison snapshot."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    slot: Literal["A", "B", "C"]
    product_id: str
    relation_id: str | None
    company_snapshot: str
    spec_snapshot: str
    price_won_snapshot: int
    g2b_url: str
    attributes: list[CatalogAttributeResponse]


class EstimateLineResponse(BaseModel):
    """One persisted line, selected attributes, and comparison snapshots."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: str
    line_no: int
    line_kind: Literal["main", "option"]
    product_id: str
    parent_product_id: str | None
    relation_id: str | None
    offer_operation: str | None
    offer_key: str | None
    item_name_snapshot: str
    spec_snapshot: str
    company_snapshot: str
    unit_snapshot: str
    unit_price_won_snapshot: int
    quantity: Decimal
    attributes: list[CatalogAttributeResponse]
    comparisons: list[EstimateComparisonResponse]


class EstimateDocumentResponse(BaseModel):
    """One complete persisted estimate document."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    created_at: str
    updated_at: str
    lines: list[EstimateLineResponse]
    export_ready: bool


class EstimateSummaryResponse(BaseModel):
    """One non-empty saved estimate list row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    updated_at: str
    line_count: int
