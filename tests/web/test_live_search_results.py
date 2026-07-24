from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx
import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport
from g2b_compare.web.app import LiveSearchOverrides, create_app
from tests.sources.test_transport import FakeResponse

NAME = "영상감시장치"
SERVICE_KEY = "live-ui-fixture-key"


def _row(operation: str, index: int, page: int) -> dict[str, str]:
    amount = 1_000_000 + index * 10_000
    return {
        "shopngCntrctNo": f"{operation}-{page}-{index}",
        "shopngCntrctSno": "1",
        "prdctIdntNo": f"{operation}-P-{page}-{index}",
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": NAME,
        "dtilPrdctClsfcNo": "4617162201",
        "prdctSpecNm": f"{NAME}, 테스트업체, MODEL-{index}, 방범감시시스템",
        "cntrctPrceAmt": str(amount),
        "prdctUnit": "조",
        "prdctImgUrl": "https://shop.g2b.go.kr/static/test-product.jpg",
        "cntrctCorpNm": "주식회사 테스트",
        "cntrctMthdNm": "다수공급자계약",
        "prdctDlvryCndtnNm": "현장설치도",
        "levDivNm": "본품",
        "cntrctEndDate": "20271231",
        "rgstDt": f"202607{20 - index:02d}1200",
    }


def _page(operation: str, page: int) -> bytes:
    rows = [_row(operation, index, page) for index in range(10)]
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": rows,
                    "numOfRows": 10,
                    "pageNo": page,
                    "totalCount": 40,
                },
            }
        },
        ensure_ascii=False,
    ).encode()


@dataclass(slots=True)
class _PageRequester:
    calls: list[tuple[str, tuple[tuple[str, str], ...], bool]] = field(
        default_factory=list
    )

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> FakeResponse:
        self.calls.append((url, params, follow_redirects))
        operation = url.rsplit("/", maxsplit=1)[-1]
        page = int(dict(params)["pageNo"])
        return FakeResponse(200, "application/json", _page(operation, page))


def _client(requester: _PageRequester) -> httpx.AsyncClient:
    adapter = ShoppingMallAdapter(HttpTransport(requester))
    app = create_app(live=LiveSearchOverrides(adapter, SERVICE_KEY))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_live_results_render_official_fields_and_real_provider_pagination() -> (
    None
):
    requester = _PageRequester()
    async with _client(requester) as client:
        response = await client.get(
            "/live",
            params={"product_name": NAME, "page": "2"},
        )

    assert response.status_code == 200
    assert response.text.count('class="product-card"') == 30
    assert "1,000,000원" in response.text
    assert "주식회사 테스트" in response.text
    assert "현장설치도" in response.text
    assert 'loading="lazy"' in response.text
    assert "ctrtItemMngNo=getMASCntrctPrdctInfoList-2-0_1" in response.text
    assert "점수" not in response.text
    assert "목표가격(원)" in response.text
    assert "<details" in response.text
    assert "page=3" in response.text
    assert "page=1" in response.text
    assert len(requester.calls) == len(tuple(Operation)[:3])
    assert all(
        ("pageNo", "2") in params and ("numOfRows", "10") in params
        for _url, params, _redirects in requester.calls
    )


@pytest.mark.asyncio
async def test_live_price_sort_is_applied_without_exposing_internal_scores() -> None:
    requester = _PageRequester()
    async with _client(requester) as client:
        response = await client.get(
            "/live",
            params={"product_name": NAME, "sort": "price_desc"},
        )

    first_high = response.text.index("1,090,000원")
    first_low = response.text.index("1,000,000원")
    assert first_high < first_low
    assert "유사도 점수" not in response.text
