"""Typed estimate drafts, snapshots, and domain errors."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, final, override


@dataclass(frozen=True, slots=True)
class EstimateLineInput:
    """One selected product snapshot ready to append to a draft."""

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


@dataclass(frozen=True, slots=True)
class EstimateLine:
    """One persisted estimate line with stable display snapshots."""

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


@dataclass(frozen=True, slots=True)
class EstimateDraft:
    """One draft and its ordered lines."""

    id: str
    title: str
    template_sha256: str
    created_at: str
    updated_at: str
    lines: tuple[EstimateLine, ...]


@dataclass(frozen=True, slots=True)
class EstimateDraftSummary:
    """One non-empty draft shown in the saved estimate list."""

    id: str
    title: str
    updated_at: str
    line_count: int


@final
class EstimateNotFoundError(Exception):
    """The requested draft or line does not exist."""

    estimate_id: str

    def __init__(self, estimate_id: str) -> None:
        """Initialize the missing identifier."""
        super().__init__(estimate_id)
        self.estimate_id = estimate_id

    @override
    def __str__(self) -> str:
        return f"estimate {self.estimate_id} not found"


@final
class EstimateFullError(Exception):
    """The fixed template cannot accept a tenth estimate line."""

    estimate_id: str

    def __init__(self, estimate_id: str) -> None:
        """Initialize the full estimate identifier."""
        super().__init__(estimate_id)
        self.estimate_id = estimate_id

    @override
    def __str__(self) -> str:
        return f"estimate {self.estimate_id} already has 9 lines"
