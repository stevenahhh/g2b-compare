from __future__ import annotations

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparators import build_comparators


def _product(product_id: str, option: str, price: int) -> RankableProduct:
    return RankableProduct(
        product_id=product_id,
        category_key=("45", "4512"),
        product_name_key="영상감시장치",
        option_text=option,
        active=True,
        price=ComparisonPrice(
            active=True,
            amount_won=price,
            unit_key="대",
            offer_key=("op", product_id),
            reason=None,
        ),
    )


def test_comparators_return_exact_three_slots_without_tolerance_filter() -> None:
    # Given: one anchor and candidates both near and far in price
    anchor = _product("A", "800만화소 30fps", 1_000_000)
    candidates = (
        _product("B", "800만화소 30fps", 1_010_000),
        _product("C", "800만화소 15fps", 4_000_000),
        _product("D", "400만화소 30fps", 900_000),
    )

    # When: comparator ranking runs
    slots = build_comparators(anchor, candidates)

    # Then: all three positions are populated regardless of request tolerance
    assert tuple(slot.rank for slot in slots) == (1, 2, 3)
    assert {slot.comparator.product_id for slot in slots if slot.comparator} == {
        "B",
        "C",
        "D",
    }


def test_comparators_fill_candidate_shortage_deterministically() -> None:
    # Given: only one eligible candidate
    anchor = _product("A", "800만화소", 1_000_000)

    # When: comparator ranking runs
    slots = build_comparators(anchor, (_product("B", "800만화소", 1_100_000),))

    # Then: remaining slots explicitly report the shortage
    assert slots[0].comparator is not None
    assert tuple(slot.status for slot in slots[1:]) == (
        "insufficient_candidates",
        "insufficient_candidates",
    )
