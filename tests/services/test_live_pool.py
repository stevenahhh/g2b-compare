from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from g2b_compare.services import live_pool
from g2b_compare.services.live_pool import fetch_live_pool
from g2b_compare.services.search_models import CategoryRef
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport
from tests.sources.test_transport import FakeResponse, ScriptedRequester

if TYPE_CHECKING:
    import httpx

OBSERVED_AT = datetime(2026, 7, 20, 1, 2, 3, tzinfo=UTC)
SERVICE_KEY = "fixture-live-pool-key"
NAME = "영상감시장치"


def _row(
    product_id: str,
    contract_no: str,
    *,
    name: str = NAME,
    price: str = "1250000",
    unit: str = "대",
    registered: str = "202607151200",
    contract_end: str = "20271231",
    supplier: str = "주식회사 최신",
) -> dict[str, str]:
    return {
        "shopngCntrctNo": contract_no,
        "shopngCntrctSno": "1",
        "prdctIdntNo": product_id,
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": name,
        "dtilPrdctClsfcNo": "4617162201",
        "prdctSpecNm": "8MP 800만화소",
        "cntrctPrceAmt": price,
        "prdctUnit": unit,
        "prdctImgUrl": "https://shop.g2b.go.kr/image/product.jpg",
        "cntrctCorpNm": supplier,
        "cntrctMthdNm": "다수공급자계약",
        "prdctDlvryCndtnNm": "현장설치도",
        "levDivNm": "본품",
        "cntrctEndDate": contract_end,
        "rgstDt": registered,
    }


def _page(rows: list[dict[str, str]], *, page_no: int = 1, total_count: int) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": rows,
                    "numOfRows": 100,
                    "pageNo": page_no,
                    "totalCount": total_count,
                },
            }
        },
        ensure_ascii=False,
    ).encode()


def _response(body: bytes) -> FakeResponse:
    return FakeResponse(200, "application/json", body)


def _adapter(
    outcomes: list[FakeResponse | httpx.TimeoutException],
) -> ShoppingMallAdapter:
    return ShoppingMallAdapter(HttpTransport(ScriptedRequester(outcomes)))


def test_fetch_live_pool_merges_matching_records_across_operations() -> None:
    # Given: the same product ID appears in all three current-offer operations.
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        _response(
            _page(
                [_row("P-1", "C-1", price="1300000", registered="202607141200")],
                total_count=1,
            )
        ),
        _response(
            _page(
                [
                    _row(
                        "P-1",
                        "C-2",
                        price="1250000",
                        registered="202607151200",
                    )
                ],
                total_count=1,
            )
        ),
        _response(
            _page(
                [_row("P-1", "C-3", price="1000", registered="202607131200")],
                total_count=1,
            )
        ),
    ]

    # When
    pool = fetch_live_pool(_adapter(outcomes), SERVICE_KEY, NAME, OBSERVED_AT)

    # Then: one merged product using one coherent latest contract record.
    assert not pool.has_next
    assert len(pool.products) == 1
    product = pool.products[0]
    assert product.rankable.product_id == "P-1"
    assert product.rankable.price.active
    assert product.rankable.price.amount_won == 1250000
    assert product.rankable.category_key == ("46171622", "4617162201")
    assert product.contract_item_key == "C-2_1"
    assert product.supplier_name == "주식회사 최신"
    assert product.image_url == "https://shop.g2b.go.kr/image/product.jpg"
    assert pool.categories == (CategoryRef("46171622", "4617162201"),)


def test_fetch_live_pool_uses_the_latest_contract_unit_without_mixing_offers() -> None:
    # Given: the same product has two offers with incompatible units.
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        _response(
            _page(
                [
                    _row(
                        "P-1",
                        "C-1",
                        price="1000",
                        unit="개",
                        registered="202607141200",
                    )
                ],
                total_count=1,
            )
        ),
        _response(
            _page(
                [
                    _row(
                        "P-1",
                        "C-2",
                        price="2000",
                        unit="세트",
                        registered="202607151200",
                    )
                ],
                total_count=1,
            )
        ),
        _response(_page([], total_count=0)),
    ]

    # When
    pool = fetch_live_pool(_adapter(outcomes), SERVICE_KEY, NAME, OBSERVED_AT)

    # Then
    assert len(pool.products) == 1
    price = pool.products[0].rankable.price
    assert price.active
    assert price.amount_won == 2000
    assert price.unit_key == "세트"


def test_fetch_live_pool_excludes_records_with_a_different_category_name() -> None:
    # Given: the provider filter returns a near-match the client must reject.
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        _response(_page([_row("P-1", "C-1", name="다른물품")], total_count=1)),
        _response(_page([], total_count=0)),
        _response(_page([], total_count=0)),
    ]

    # When
    pool = fetch_live_pool(_adapter(outcomes), SERVICE_KEY, NAME, OBSERVED_AT)

    # Then
    assert pool.products == ()
    assert pool.categories == ()


def test_fetch_live_pool_requests_the_selected_provider_page() -> None:
    # Given: every operation reports more rows after the selected page.
    huge_total = live_pool.PAGE_SIZE * 10
    rows_per_page = 2
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        _response(
            _page(
                [_row(f"P-2-{index}", f"C-2-{index}") for index in range(2)],
                page_no=2,
                total_count=huge_total,
            )
        ),
        _response(_page([], total_count=0)),
        _response(_page([], total_count=0)),
    ]
    adapter = _adapter(outcomes)

    # When
    pool = fetch_live_pool(adapter, SERVICE_KEY, NAME, OBSERVED_AT, source_page=2)

    # Then
    assert pool.has_next
    assert len(pool.products) == rows_per_page
    calls = adapter.transport.requester.calls
    assert len(calls) == 3
    assert all(("pageNo", "2") in params for _url, params, _redirects in calls)
    assert all(
        ("numOfRows", str(live_pool.PAGE_SIZE)) in params
        for _url, params, _redirects in calls
    )


def test_fetch_live_pool_excludes_expired_contracts() -> None:
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        _response(
            _page(
                [
                    _row("OLD", "C-OLD", contract_end="20260719"),
                    _row("CURRENT", "C-CURRENT", contract_end="20260720"),
                ],
                total_count=2,
            )
        ),
        _response(_page([], total_count=0)),
        _response(_page([], total_count=0)),
    ]

    pool = fetch_live_pool(_adapter(outcomes), SERVICE_KEY, NAME, OBSERVED_AT)

    assert tuple(item.rankable.product_id for item in pool.products) == ("CURRENT",)
