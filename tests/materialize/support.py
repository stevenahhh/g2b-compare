from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.materialize.products import SourceOffer

if TYPE_CHECKING:
    from g2b_compare.contracts.quota import Operation


@dataclass(frozen=True, slots=True)
class OfferOverride:
    product_id: str = "P-1"
    name: str = "영상감시장치"
    price: str = "1200000"
    unit: str = "대"
    updated_at: str = "2026-07-15T00:00:00Z"
    active: bool = True


DEFAULT_OVERRIDE = OfferOverride()


def offer(
    operation: Operation,
    key: str,
    override: OfferOverride = DEFAULT_OVERRIDE,
) -> SourceOffer:
    return SourceOffer(
        operation=operation,
        offer_key=key,
        product_id=override.product_id,
        category_no="46171622",
        detail_category_no="4617162201",
        product_name_raw=override.name,
        spec_name="8MP",
        detail="800만 화소",
        characteristic="방수",
        contract_price_raw=override.price,
        unit_raw=override.unit,
        product_unit_price_raw="1190000",
        active=override.active,
        source_updated_at=override.updated_at,
        raw_fields_json='{"prdctIdntNo":"P-1"}',
    )
