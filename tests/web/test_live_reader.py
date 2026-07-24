from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from g2b_compare.services.release_models import ReleasePin
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchRequest
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport
from g2b_compare.web.live_reader import LiveReaderNotPinnedError, WebLiveSearchReader
from tests.sources.test_transport import FakeResponse, ScriptedRequester

if TYPE_CHECKING:
    import httpx

NAME = "영상감시장치"


def _row(product_id: str, contract_no: str) -> dict[str, str]:
    return {
        "shopngCntrctNo": contract_no,
        "shopngCntrctSno": "1",
        "prdctIdntNo": product_id,
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": NAME,
        "dtilPrdctClsfcNo": "4617162201",
        "prdctSpecNm": "8MP 800만화소",
        "cntrctPrceAmt": "1250000",
        "prdctUnit": "대",
        "prdctImgUrl": "https://shop.g2b.go.kr/image/product.jpg",
        "rgstDt": "202607151200",
    }


def _page(rows: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": rows,
                    "numOfRows": 100,
                    "pageNo": 1,
                    "totalCount": len(rows),
                },
            }
        },
        ensure_ascii=False,
    ).encode()


def _reader(
    outcomes: list[FakeResponse | httpx.TimeoutException],
) -> tuple[WebLiveSearchReader, ScriptedRequester]:
    requester = ScriptedRequester(outcomes)
    adapter = ShoppingMallAdapter(HttpTransport(requester))
    reader = WebLiveSearchReader(
        NAME,
        adapter,
        "fixture-key",
        clock=lambda: datetime(2026, 7, 20, 1, 0, 0, tzinfo=UTC),
    )
    return reader, requester


def _dummy_pin() -> ReleasePin:
    sha = "0" * 64
    return ReleasePin(0, 0, 0, 0, 0, "v1", "v1", "live-v1", sha, sha, sha, sha, sha, "")


def test_categories_and_exact_products_read_before_pinning_raises() -> None:
    reader, _requester = _reader([])

    with pytest.raises(LiveReaderNotPinnedError):
        _ = reader.categories(_dummy_pin())


def test_pin_active_release_fetches_exactly_once_across_repeated_calls() -> None:
    # Given: one product across the three current-offer operations.
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        FakeResponse(200, "application/json", _page([_row("P-1", "C-1")])),
        FakeResponse(200, "application/json", _page([])),
        FakeResponse(200, "application/json", _page([])),
    ]
    reader, requester = _reader(outcomes)

    # When: pinning twice, as a defensive caller might.
    first = reader.pin_active_release()
    second = reader.pin_active_release()

    # Then: only the first three operation calls ever fire.
    assert first == second
    assert len(requester.calls) == 3
    assert reader.categories(first) == reader.categories(second)
    assert len(reader.exact_products(first, NAME)) == 1


def test_execute_search_accepts_the_reader_as_a_full_search_reader() -> None:
    # Given: a live reader wired exactly as the /live route would build one.
    outcomes: list[FakeResponse | httpx.TimeoutException] = [
        FakeResponse(200, "application/json", _page([_row("P-1", "C-1")])),
        FakeResponse(200, "application/json", _page([])),
        FakeResponse(200, "application/json", _page([])),
    ]
    reader, _requester = _reader(outcomes)
    request = SearchRequest.model_validate({"product_name": NAME})

    # When
    response = execute_search(request, reader)

    # Then: the full ranking/comparator pipeline runs unmodified.
    assert response.status == "ok"
    assert response.total_results == 1
    assert response.results[0].product.rankable.product_id == "P-1"
    assert not reader.truncated
