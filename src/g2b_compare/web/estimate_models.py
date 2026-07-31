"""Shared estimate comparison constants and records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from g2b_compare.priority_models import ProductAttribute

COMPARISON_SLOT_COUNT: Final = 3
RELATION_REQUIRED_DETAIL: Final = "검증된 본품/옵션 관계가 필요함"
ALTERNATIVE_COUNT: Final = COMPARISON_SLOT_COUNT - 1
PRICE_LADDER_PERCENTAGES: Final = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110)
KOREANET_COMPANY: Final = "주식회사 코리아넷"


@dataclass(frozen=True, slots=True)
class ComparisonView:
    """One comparison candidate shown in the estimate editor."""

    slot: str
    product_id: str
    relation_id: str | None
    company: str
    spec: str
    price_won: int
    attributes: tuple[ProductAttribute, ...] = ()
    detail_url: str = ""


@dataclass(frozen=True, slots=True)
class MainCandidate:
    """One ranked main-product candidate and deterministic key."""

    view: ComparisonView
    source_row: int
    key: tuple[int, int, int, int, int, int, int, str]


@dataclass(frozen=True, slots=True)
class OptionCandidate:
    """One option candidate with display and matching text."""

    view: ComparisonView
    item_name: str
    match_text: str
