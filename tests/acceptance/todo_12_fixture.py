from __future__ import annotations

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparators import (
    CuratedRelation,
    ObservedOptionRole,
    ProductRecord,
)


def product_record(
    product_id: str,
    *,
    option: str = "800만화소 30fps",
    price: int = 1_000_000,
    unit: str = "대",
    category: tuple[str, str] = ("45", "4512"),
) -> ProductRecord:
    rankable = RankableProduct(
        product_id=product_id,
        category_key=category,
        product_name_key="영상감시장치",
        option_text=option,
        active=True,
        price=ComparisonPrice(
            active=True,
            amount_won=price,
            unit_key=unit,
            offer_key=("op", product_id),
            reason=None,
        ),
    )
    role = ObservedOptionRole(
        3,
        f"row-{product_id}",
        "delivery",
        "1",
        "0",
        "추가선택",
        "2026-07-16",
    )
    relation = CuratedRelation(
        f"rel-{product_id}",
        product_id,
        f"child-{product_id}",
        "workbook",
        "f" * 64,
        "품목",
        9,
    )
    return ProductRecord(
        rankable,
        "영상감시장치",
        "2026-07-16",
        "1/1",
        (role,),
        (relation,),
    )
