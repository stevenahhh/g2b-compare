from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import (
    CatalogRecord,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)
from g2b_compare.web.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.contracts.redact import JsonValue


def _record(sequence: int) -> CatalogRecord:
    product_id = f"25{sequence:06d}"
    contract_number = f"0023H{sequence:06d}"
    raw: dict[str, JsonValue] = {
        "shopngCntrctNo": contract_number,
        "shopngCntrctSno": "1",
        "prdctIdntNo": product_id,
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": "영상감시장치",
        "dtilPrdctClsfcNo": "4617162201",
        "prdctSpecNm": f"영상감시장치 800만화소 {sequence}",
        "cntrctPrceAmt": str(1_000_000 + sequence),
        "cntrctCorpNm": f"공급사 {sequence}",
        "prdctUnit": "조",
        "cntrctMthdNm": "다수공급자계약",
        "prdctDlvryCndtnNm": "현장설치도",
        "dlvrTmlmtDaynum": "60",
        "cntrctEndDate": "20271231",
    }
    return CatalogRecord(
        identity=SourceIdentity(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            (contract_number, "1"),
        ),
        product_id=product_id,
        classification_number="46171622",
        category_name="영상감시장치",
        detail_category_number="4617162201",
        spec_name=f"영상감시장치 800만화소 {sequence}",
        contract_price=str(1_000_000 + sequence),
        image_url="",
        timestamp=TimestampEvidence(
            "20260721",
            TimestampOrigin.OBSERVED_AT_FALLBACK,
            0,
        ),
        raw_fields=raw,
    )


@pytest.mark.asyncio
async def test_main_app_exposes_data_and_priority_pages_on_one_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    PriorityStore(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        data_response = await client.get("/data")
        priority_response = await client.get("/priority")

    assert data_response.status_code == 200
    assert "데이터 관리" in data_response.text
    assert priority_response.status_code == 200
    assert "우선수집 물품 DB" in priority_response.text


@pytest.mark.asyncio
async def test_root_uses_priority_catalog_and_returns_exactly_thirty_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = PriorityStore(database)
    store.save_catalog_page(
        company_name="통합 공급사",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=1_000,
        total_count=31,
        records=tuple(_record(index) for index in range(1, 32)),
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/", params={"product_name": "영상감시장치"})

    assert response.status_code == 200
    assert response.text.count('class="product-card"') == 30
    assert 'class="catalog-scroll-region"' in response.text
    assert 'tabindex="0"' in response.text
    assert 'class="next-page"' in response.text
    assert 'name="q"' in response.text
    assert "품명, 규격, 업체명, 물품번호" in response.text
    assert 'name="product_name"' not in response.text
    assert 'name="spec_text"' not in response.text


@pytest.mark.asyncio
async def test_catalog_sorts_and_serves_the_next_infinite_scroll_chunk(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = PriorityStore(database)
    store.save_catalog_page(
        company_name="통합 공급사",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=1_000,
        total_count=31,
        records=tuple(_record(index) for index in range(1, 32)),
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/",
            params={"q": "250000", "sort": "price_desc"},
        )
        fragment = await client.get(
            "/catalog/items",
            params={"q": "250000", "sort": "price_desc", "page": 2},
        )

    assert response.status_code == 200
    assert response.text.index("25000031") < response.text.index("25000030")
    assert '<script src="/static/catalog.js" defer></script>' in response.text
    assert 'value="price_desc" selected' in response.text
    assert fragment.status_code == 200
    assert fragment.text.count('class="product-card"') == 1
    assert "25000001" in fragment.text
    assert fragment.headers["x-catalog-next-page"] == ""


@pytest.mark.asyncio
async def test_main_navigation_names_only_integrated_mvp_sections(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    PriorityStore(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/live")

    assert response.status_code == 200
    assert 'href="/">물품 검색</a>' in response.text
    assert 'href="/estimates">관급내역</a>' in response.text
    assert 'href="/data">데이터 관리</a>' in response.text
