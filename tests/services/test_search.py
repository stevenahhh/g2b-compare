from __future__ import annotations

from decimal import Decimal
from typing import final

import pytest
from pydantic import ValidationError

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparators import (
    ComparatorCacheError,
    ComparatorView,
    CuratedRelation,
    ObservedOptionRole,
    ProductRecord,
    compare_product,
)
from g2b_compare.services.release_models import ReleasePin
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import (
    CategoryRef,
    SearchRequest,
    SearchServiceError,
)

PIN = ReleasePin(
    bundle_id=7,
    ready_attempt_no=2,
    materialization_id=11,
    index_version_id=13,
    relation_snapshot_id=17,
    ranking_version="v1",
    normalization_version="norm-v1",
    materialization_policy_version="materialization-v1",
    materialization_source_sha="materialization-sha",
    index_artifact_sha="index-sha",
    index_manifest_sha="index-manifest-sha",
    relation_source_manifest_sha="relation-manifest-sha",
    relation_content_sha="relation-content-sha",
    data_as_of="2026-07-16",
)
CATEGORIES = (CategoryRef("45", "4512"), CategoryRef("45", "4513"))


@final
class _Reader:
    def __init__(
        self,
        products: tuple[ProductRecord, ...] = (),
        categories: tuple[CategoryRef, ...] = CATEGORIES,
        cache: tuple[tuple[str, tuple[ComparatorView, ...]], ...] = (),
        pin: ReleasePin = PIN,
        *,
        stale: bool = False,
    ) -> None:
        self.products: tuple[ProductRecord, ...] = products
        self.category_rows: tuple[CategoryRef, ...] = categories
        self.cache: tuple[tuple[str, tuple[ComparatorView, ...]], ...] = cache
        self.pin: ReleasePin = pin
        self.pin_calls: int = 0
        self.stale: bool = stale
        self.seen_pins: list[ReleasePin] = []

    def pin_active_release(self) -> ReleasePin:
        self.pin_calls += 1
        return self.pin

    def is_stale(self, pin: ReleasePin) -> bool:
        self.seen_pins.append(pin)
        return self.stale

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        self.seen_pins.append(pin)
        return self.category_rows

    def exact_products(
        self, pin: ReleasePin, product_name: str
    ) -> tuple[ProductRecord, ...]:
        self.seen_pins.append(pin)
        return self.products if product_name == "영상감시장치" else ()

    def cached_comparators(
        self, pin: ReleasePin, anchor_id: str
    ) -> tuple[ComparatorView, ...] | None:
        self.seen_pins.append(pin)
        return next((value for key, value in self.cache if key == anchor_id), None)


def _record(
    product_id: str,
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
        3, f"row-{product_id}", "delivery", "1", "0", "추가", "2026"
    )
    relation = CuratedRelation(
        f"rel-{product_id}", product_id, "child", "workbook", "sha", "sheet", 9
    )
    return ProductRecord(
        rankable, "영상감시장치", "2026-07-16", "1/1", (role,), (relation,)
    )


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"product_name": "x", "target_price_won": 0}, "invalid_price_constraint"),
        ({"product_name": "x", "price_unit": "대"}, "price_requires_target"),
        (
            {"product_name": "x", "price_tolerance_pct": Decimal(25)},
            "tolerance_requires_target",
        ),
        (
            {"product_name": "x", "detail_category_code": "4512"},
            "detail_requires_category",
        ),
        ({"product_name": "x" * 101}, "query_too_long"),
        ({"product_name": "x", "page": 0}, "page_overflow"),
    ],
)
def test_search_request_rejects_invalid_shape_in_contract_order(
    values: dict[str, str | int | Decimal], code: str
) -> None:
    # Given: one invalid public request shape
    # When/Then: parsing fails with the stable service code
    with pytest.raises(ValidationError, match=code):
        _ = SearchRequest.model_validate(values)


def test_empty_exact_name_returns_no_matches_with_one_request_pin() -> None:
    # Given: an active release without the requested exact name
    reader = _Reader()

    # When: search executes
    response = execute_search(SearchRequest(product_name="영상감시장치"), reader)

    # Then: no-match is typed and all reads used the same pin
    assert (response.status, response.total_results, response.results) == (
        "no-matches",
        0,
        (),
    )
    assert reader.pin_calls == 1
    assert reader.seen_pins
    assert all(item is PIN for item in reader.seen_pins)


def test_single_category_auto_selects_and_preserves_provenance() -> None:
    # Given: one exact category tuple with event and curated provenance
    product = _record("A")

    # When: search executes
    response = execute_search(
        SearchRequest(product_name="영상감시장치", spec_text="800만화소"),
        _Reader((product,)),
    )

    # Then: the exact tuple and both evidence kinds survive
    assert response.selected_category == CategoryRef("45", "4512")
    assert response.results[0].product.observed_option_roles[0].role_raw == "추가"
    assert response.results[0].product.curated_relations[0].source_type == "workbook"


@pytest.mark.parametrize(
    ("search_request", "code"),
    [
        (SearchRequest(product_name="영상감시장치"), "ambiguous_category"),
        (
            SearchRequest(product_name="영상감시장치", category_code="45"),
            "ambiguous_detail_category",
        ),
        (
            SearchRequest(product_name="영상감시장치", category_code="99"),
            "unknown_category",
        ),
        (
            SearchRequest(
                product_name="영상감시장치",
                category_code="45",
                detail_category_code="9999",
            ),
            "unknown_detail_category",
        ),
    ],
)
def test_category_matrix_errors_are_stable(
    search_request: SearchRequest, code: str
) -> None:
    # Given: exact-name rows span two detail categories
    rows = (_record("A"), _record("B", category=("45", "4513")))

    # When/Then: category resolution returns one stable semantic code
    with pytest.raises(SearchServiceError, match=code):
        _ = execute_search(search_request, _Reader(rows))


def test_price_tolerance_defaults_to_twenty_five_and_flags_outside_rows() -> None:
    # Given: one exact pool with prices inside and outside the default interval
    rows = (_record("inside", price=1_100_000), _record("outside", price=2_000_000))
    request = SearchRequest(product_name="영상감시장치", target_price_won=1_000_000)

    # When: query-anchored scoring and ordering run
    response = execute_search(request, _Reader(rows))

    # Then: all rows remain, inside sorts first, and default tolerance is explicit
    assert response.total_results == 2
    assert response.price_tolerance_pct == Decimal("25.00")
    assert tuple(item.within_price_tolerance for item in response.results) == (
        True,
        False,
    )


def test_price_unit_is_required_for_a_nonempty_mixed_unit_pool() -> None:
    # Given: a target price and two canonical units
    rows = (_record("A", unit="대"), _record("B", unit="개"))

    # When/Then: unit resolution fails with sorted choices
    with pytest.raises(SearchServiceError, match="price_unit_required") as captured:
        _ = execute_search(
            SearchRequest(product_name="영상감시장치", target_price_won=1_000_000),
            _Reader(rows),
        )
    assert captured.value.choices == ("개", "대")


def test_page_overflow_is_rejected_before_comparator_resolution() -> None:
    # Given: one result but a request for page two
    request = SearchRequest(product_name="영상감시장치", page=2)

    # When/Then: overflow is a stable semantic failure
    with pytest.raises(SearchServiceError, match="page_overflow"):
        _ = execute_search(request, _Reader((_record("A"),)))


def test_empty_pool_page_overflow_is_rejected() -> None:
    # Given: no exact results and a request beyond the first page
    request = SearchRequest(product_name="영상감시장치", page=2)

    # When/Then: an empty pool still enforces the pagination boundary
    with pytest.raises(SearchServiceError, match="page_overflow"):
        _ = execute_search(request, _Reader())


def test_explicit_zero_tolerance_is_not_replaced_by_the_default() -> None:
    # Given: exact and non-exact prices with an explicit zero-percent tolerance
    rows = (_record("exact"), _record("near", price=1_000_001))
    request = SearchRequest(
        product_name="영상감시장치",
        target_price_won=1_000_000,
        price_tolerance_pct=Decimal(0),
    )

    # When: search applies the inclusive interval
    response = execute_search(request, _Reader(rows))

    # Then: zero remains explicit and only the exact integer price is inside
    assert response.price_tolerance_pct == Decimal("0.00")
    assert tuple(item.within_price_tolerance for item in response.results) == (
        True,
        False,
    )


def test_cached_and_uncached_paths_return_identical_typed_response() -> None:
    # Given: four exact products and cache rows computed from the same release data
    rows = tuple(
        _record(letter, price=1_000_000 + index * 10_000)
        for index, letter in enumerate("ABCD")
    )
    cache = tuple((row.rankable.product_id, compare_product(row, rows)) for row in rows)
    request = SearchRequest(product_name="영상감시장치", spec_text="800만화소")

    # When: uncached and cached paths execute
    uncached = execute_search(request, _Reader(rows))
    cached = execute_search(request, _Reader(rows, cache=cache))

    # Then: both return equal typed responses
    assert cached == uncached


def test_stale_release_and_corrupt_cache_fail_closed() -> None:
    # Given: one stale pin and one incomplete cache payload
    product = _record("A")

    # When/Then: both boundaries fail with stable codes
    with pytest.raises(SearchServiceError, match="stale_snapshot"):
        _ = execute_search(
            SearchRequest(product_name="영상감시장치"),
            _Reader((product,), stale=True),
        )
    with pytest.raises(ComparatorCacheError, match="corrupt_cache"):
        _ = execute_search(
            SearchRequest(product_name="영상감시장치"),
            _Reader(
                (product,), cache=(("A", compare_product(product, (product,))[:2]),)
            ),
        )
