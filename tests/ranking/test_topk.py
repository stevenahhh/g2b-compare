from __future__ import annotations

from itertools import permutations
from typing import TYPE_CHECKING

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking import features
from g2b_compare.ranking.topk import RankableProduct, top_three

if TYPE_CHECKING:
    import pytest

    from g2b_compare.search.index_builder import IndexBuildRequest, IndexBundle


def _product(
    product_id: str,
    option: str = "800만화소",
    *,
    active: bool = True,
) -> RankableProduct:
    return RankableProduct(
        product_id=product_id,
        category_key=("4512", "451215"),
        product_name_key="영상감시장치",
        option_text=option,
        active=active,
        price=ComparisonPrice(
            active=True,
            amount_won=1_000_000,
            unit_key="대",
            offer_key=("op", product_id),
            reason=None,
        ),
    )


def test_top_three_deduplicates_self_and_returns_exact_slots() -> None:
    anchor = _product("A")
    slots = top_three(
        anchor,
        (_product("C"), _product("B"), _product("B"), anchor),
    )

    assert len(slots) == 3
    identifiers = [
        slot.comparator.product_id if slot.comparator else None for slot in slots
    ]
    assert identifiers == [
        "B",
        "C",
        None,
    ]
    assert slots[2].status == "insufficient_candidates"


def test_d_zero_is_not_candidate_shortage() -> None:
    anchor = _product("A", "")
    candidate = _product("B", "")
    anchor = RankableProduct(
        anchor.product_id,
        anchor.category_key,
        anchor.product_name_key,
        anchor.option_text,
        anchor.active,
        ComparisonPrice(
            active=False,
            amount_won=None,
            unit_key=None,
            offer_key=None,
            reason="missing-price",
        ),
    )
    candidate = RankableProduct(
        candidate.product_id,
        candidate.category_key,
        candidate.product_name_key,
        candidate.option_text,
        candidate.active,
        ComparisonPrice(
            active=False,
            amount_won=None,
            unit_key=None,
            offer_key=None,
            reason="missing-price",
        ),
    )

    slots = top_three(anchor, (candidate,))

    assert slots[0].comparator is not None
    assert slots[0].status == "no_comparison_evidence"
    assert slots[1].status == "insufficient_candidates"


def test_100_shuffles_produce_identical_order() -> None:
    anchor = _product("A")
    candidates = [_product("D"), _product("B"), _product("C")]
    expected = ("B", "C", "D")
    arrangements = tuple(permutations(candidates))

    for seed in range(100):
        slots = top_three(anchor, arrangements[seed % len(arrangements)])
        identifiers = tuple(
            slot.comparator.product_id for slot in slots if slot.comparator
        )
        assert identifiers == expected


def test_each_ranking_request_builds_one_global_lexical_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    build_index = features.build_index

    def counted(request: IndexBuildRequest) -> IndexBundle:
        nonlocal calls
        calls += 1
        return build_index(request)

    monkeypatch.setattr(features, "build_index", counted)
    anchor = _product("A")
    candidates = (_product("D", "4MP"), _product("B"), _product("C", "8MP"))

    first = top_three(anchor, candidates)
    assert calls == 1
    second = top_three(anchor, tuple(reversed(candidates)))

    assert calls == 2
    assert repr(first).encode() == repr(second).encode()
