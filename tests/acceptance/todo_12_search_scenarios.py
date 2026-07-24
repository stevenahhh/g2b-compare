from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Final, final

from pydantic import ValidationError

from g2b_compare.db.migrate import migrate
from g2b_compare.services.comparators import (
    ComparatorCacheError,
    ComparatorView,
    ProductRecord,
    compare_product,
    validate_cached,
)
from g2b_compare.services.release import ReleaseContractError, pin_active_release
from g2b_compare.services.release_models import ReleasePin
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import (
    CategoryRef,
    SearchRequest,
    SearchServiceError,
)

from .todo_12_fixture import product_record

PIN: Final = ReleasePin(
    7,
    2,
    11,
    13,
    17,
    "v1",
    "norm-v1",
    "policy-v1",
    "a" * 64,
    "b" * 64,
    "c" * 64,
    "d" * 64,
    "e" * 64,
    "2026-07-16",
)
CATEGORIES: Final = (
    CategoryRef("45", "4512"),
    CategoryRef("45", "4513"),
    CategoryRef("46", "4612"),
)

REQUEST_FAILURES: Final[dict[str, dict[str, str | int | Decimal]]] = {
    "detail-without-upper": {
        "product_name": "영상감시장치",
        "detail_category_code": "4512",
    },
    "price-requires-target": {
        "product_name": "영상감시장치",
        "price_unit": "대",
    },
    "tolerance-requires-target": {
        "product_name": "영상감시장치",
        "price_tolerance_pct": Decimal(25),
    },
    "invalid-price-constraint": {
        "product_name": "영상감시장치",
        "target_price_won": 0,
    },
    "invalid-price-before-unknown-category": {
        "product_name": "영상감시장치",
        "category_code": "99",
        "target_price_won": 0,
    },
    "price-crossfield-before-category": {
        "product_name": "영상감시장치",
        "category_code": "99",
        "price_unit": "대",
    },
    "query-too-long": {"product_name": "가" * 101},
}


@final
class ScenarioReader:
    __slots__ = ("cache", "category_rows", "pin_calls", "products", "stale")

    def __init__(
        self,
        products: tuple[ProductRecord, ...] = (),
        categories: tuple[CategoryRef, ...] | None = None,
        cache: tuple[tuple[str, tuple[ComparatorView, ...]], ...] = (),
        *,
        stale: bool = False,
    ) -> None:
        self.products = products
        self.category_rows = CATEGORIES if categories is None else categories
        self.cache = cache
        self.stale = stale
        self.pin_calls = 0

    def pin_active_release(self) -> ReleasePin:
        self.pin_calls += 1
        return PIN

    def is_stale(self, pin: ReleasePin) -> bool:
        _ = pin
        return self.stale

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        _ = pin
        return self.category_rows

    def exact_products(
        self, pin: ReleasePin, product_name: str
    ) -> tuple[ProductRecord, ...]:
        _ = pin
        return self.products if product_name == "영상감시장치" else ()

    def cached_comparators(
        self, pin: ReleasePin, anchor_id: str
    ) -> tuple[ComparatorView, ...] | None:
        _ = pin
        return next((value for key, value in self.cache if key == anchor_id), None)


def observe_search(scenario: str, database_path: str) -> tuple[str, str]:
    if scenario in REQUEST_FAILURES:
        result = _request_error(REQUEST_FAILURES[scenario])
    elif scenario == "empty-db":
        result = _empty_database(database_path)
    elif scenario == "no-result":
        result = _response(SearchRequest(product_name="미존재"), ScenarioReader())
    elif scenario == "empty-pool-with-supplied-unit":
        request = SearchRequest(
            product_name="미존재",
            target_price_won=1_000,
            price_unit="대",
        )
        result = _response(request, ScenarioReader())
    elif scenario == "empty-pool-before-unit-resolution":
        request = SearchRequest(product_name="미존재", target_price_won=1_000)
        result = _response(request, ScenarioReader())
    elif scenario == "candidate-0-2":
        result = _candidate_shortage()
    elif scenario == "corrupt-cache":
        result = _corrupt_cache()
    else:
        result = _service_scenario(scenario)
    return result


def _request_error(
    values: dict[str, str | int | Decimal],
) -> tuple[str, str]:
    try:
        _ = SearchRequest.model_validate(values)
    except ValidationError as error:
        return type(error).__name__, str(error)
    detail = "request unexpectedly accepted"
    raise AssertionError(detail)


def _empty_database(database_path: str) -> tuple[str, str]:
    path = Path(database_path)
    migrate(path)
    try:
        _ = pin_active_release(path)
    except ReleaseContractError as error:
        return type(error).__name__, str(error)
    detail = "empty database unexpectedly had an active release"
    raise AssertionError(detail)


def _response(request: SearchRequest, reader: ScenarioReader) -> tuple[str, str]:
    response = execute_search(request, reader)
    return type(response).__name__, (
        f"status={response.status}; total={response.total_results}; "
        f"pin-calls={reader.pin_calls}"
    )


def _service_scenario(scenario: str) -> tuple[str, str]:
    first = product_record("A")
    detail = product_record("B", category=("45", "4513"))
    other = product_record("C", category=("46", "4612"))
    request, reader = _service_inputs(scenario, first, detail, other)
    try:
        _ = execute_search(request, reader)
    except SearchServiceError as error:
        return type(error).__name__, str(error)
    detail = f"service scenario unexpectedly succeeded: {scenario}"
    raise AssertionError(detail)


def _service_inputs(
    scenario: str,
    first: ProductRecord,
    detail: ProductRecord,
    other: ProductRecord,
) -> tuple[SearchRequest, ScenarioReader]:
    if scenario == "ambiguous-category":
        result = (
            SearchRequest(product_name="영상감시장치"),
            ScenarioReader((first, other)),
        )
    elif scenario == "upper-only-ambiguous":
        request = SearchRequest(product_name="영상감시장치", category_code="45")
        result = request, ScenarioReader((first, detail))
    elif scenario == "unknown-category":
        request = SearchRequest(product_name="영상감시장치", category_code="99")
        result = request, ScenarioReader((first,))
    elif scenario == "unknown-detail-category":
        request = SearchRequest(
            product_name="영상감시장치",
            category_code="45",
            detail_category_code="4599",
        )
        result = request, ScenarioReader((first,))
    elif scenario == "detail-parent-mismatch":
        request = SearchRequest(
            product_name="영상감시장치",
            category_code="45",
            detail_category_code="4612",
        )
        result = request, ScenarioReader((first,))
    elif scenario == "price-unit-required":
        request = SearchRequest(product_name="영상감시장치", target_price_won=1_000_000)
        result = request, ScenarioReader((first, product_record("U", unit="개")))
    elif scenario == "unknown-price-unit":
        request = SearchRequest(
            product_name="영상감시장치",
            target_price_won=1_000_000,
            price_unit="세트",
        )
        result = request, ScenarioReader((first,))
    elif scenario == "stale-snapshot":
        result = (
            SearchRequest(product_name="영상감시장치"),
            ScenarioReader((first,), stale=True),
        )
    elif scenario == "page-overflow":
        request = SearchRequest(product_name="영상감시장치", page=2)
        result = request, ScenarioReader((first,))
    else:
        detail_text = f"unknown search scenario: {scenario}"
        raise AssertionError(detail_text)
    return result


def _candidate_shortage() -> tuple[str, str]:
    pool = (product_record("A"), product_record("B"), product_record("C"))
    shortage_counts = tuple(
        sum(
            view.status == "insufficient_candidates"
            for view in compare_product(row, pool)
        )
        for row in pool
    )
    return "ComparatorView", f"shortages={shortage_counts}; slots=3"


def _corrupt_cache() -> tuple[str, str]:
    anchor = product_record("A")
    slots = compare_product(anchor, (anchor, product_record("B")))[:2]
    try:
        _ = validate_cached("A", slots)
    except ComparatorCacheError as error:
        return type(error).__name__, str(error)
    detail = "incomplete cache unexpectedly validated"
    raise AssertionError(detail)
