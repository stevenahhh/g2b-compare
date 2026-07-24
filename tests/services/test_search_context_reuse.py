from __future__ import annotations

from typing import TYPE_CHECKING, final

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.features import prepare_feature_context
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparator_models import ComparatorView, ProductRecord
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import CategoryRef, SearchRequest
from tests.services.test_search import PIN

if TYPE_CHECKING:
    import pytest

    from g2b_compare.ranking.features import PreparedFeatureContext
    from g2b_compare.services.release_models import ReleasePin


@final
class _UncachedReader:
    def __init__(self, products: tuple[ProductRecord, ...]) -> None:
        self._products = products

    def pin_active_release(self) -> ReleasePin:
        return PIN

    def is_stale(self, pin: ReleasePin) -> bool:
        _ = pin
        return False

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        _ = pin
        return (CategoryRef("45", "4512"),)

    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        _ = pin, product_name
        return self._products

    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        _ = pin, anchor_id
        return None


def _record(index: int) -> ProductRecord:
    product_id = f"P-{index:03d}"
    rankable = RankableProduct(
        product_id=product_id,
        category_key=("45", "4512"),
        product_name_key="영상감시장치",
        option_text="800만화소 30fps",
        active=True,
        price=ComparisonPrice(
            active=True,
            amount_won=1_000_000,
            unit_key="대",
            offer_key=("offer", product_id),
            reason=None,
        ),
    )
    return ProductRecord(rankable, "영상감시장치", "2026-07-18", "1/1")


def test_uncached_fifty_row_search_prepares_comparator_context_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = tuple(_record(index) for index in range(50))
    prepared = prepare_feature_context(
        tuple(item.rankable.option_text for item in products)
    )
    calls = 0

    def counted_prepare(
        _corpus: tuple[str, ...],
    ) -> PreparedFeatureContext:
        nonlocal calls
        calls += 1
        return prepared

    monkeypatch.setattr(
        "g2b_compare.ranking.topk.prepare_feature_context",
        counted_prepare,
    )

    response = execute_search(
        SearchRequest(
            product_name="영상감시장치",
            category_code="45",
            detail_category_code="4512",
            spec_text="800만화소",
        ),
        _UncachedReader(products),
    )

    assert calls == 1
    assert len(response.results) == 50
    for result in response.results:
        anchor_id = result.product.rankable.product_id
        expected = tuple(
            item.rankable.product_id
            for item in products
            if item.rankable.product_id != anchor_id
        )[:3]
        actual = tuple(
            slot.candidate.rankable.product_id
            for slot in result.comparators
            if slot.candidate is not None
        )
        assert actual == expected
