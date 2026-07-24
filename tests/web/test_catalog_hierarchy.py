from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import httpx
import pytest
from playwright.async_api import async_playwright

from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import (
    CatalogRecord,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)
from g2b_compare.web.app import create_app

MVP_CSS = Path("src/g2b_compare/web/static/mvp.css").resolve()


class _ViewportMetrics(TypedDict):
    documentWidth: int
    viewportWidth: int
    panelRight: float


def _record(product_id: str, name: str, image_url: str = "") -> CatalogRecord:
    return CatalogRecord(
        identity=SourceIdentity(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            (f"CONTRACT-{product_id}", "1"),
        ),
        product_id=product_id,
        classification_number="46171622",
        category_name=name,
        detail_category_number="4617162201",
        spec_name=f"{name} 본체 규격",
        contract_price="1000000",
        image_url=image_url,
        timestamp=TimestampEvidence(
            "2026-07-21T00:00:00+00:00",
            TimestampOrigin.OBSERVED_AT_FALLBACK,
            0,
        ),
        raw_fields={
            "cntrctCorpNm": "공급사 A",
            "prdctUnit": "조",
            "cntrctMthdNm": "다수공급자계약",
        },
    )


def _seed_hierarchy(database: Path) -> None:
    store = PriorityStore(database)
    products = (
        _record("25000001", "영상감시장치", "https://example.test/main.jpg"),
        _record("25000002", "열화상카메라"),
        _record("25000003", "출입통제장치"),
        _record("26000001", "저장장치 옵션", "https://example.test/option.jpg"),
    )
    store.save_catalog_page(
        company_name="공급사 A",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=10,
        total_count=len(products),
        records=products,
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    with sqlite3.connect(database) as connection:
        _ = connection.executemany(
            "INSERT INTO priority_options VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    1,
                    "공급사 A",
                    "추가선택품목",
                    "26000001",
                    "저장장치",
                    "8TB 확장",
                    10,
                    "",
                ),
                (
                    2,
                    "공급사 A",
                    "추가선택품목",
                    "26000002",
                    "센서",
                    "열화상",
                    20,
                    "",
                ),
            ),
        )
        _ = connection.executemany(
            """
            INSERT INTO verified_product_options VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "relation-a",
                    str(Operation.GET_MAS_CONTRACT_PRODUCT_INFO),
                    "offer-a",
                    "25000001",
                    "26000001",
                    "additional",
                    1,
                    "공급사 A",
                    "[26000001] 8TB 확장 저장장치",
                    10,
                    "https://shop.g2b.go.kr/a",
                    "2026-07-21T00:00:00+00:00",
                    1,
                ),
                (
                    "relation-b",
                    str(Operation.GET_MAS_CONTRACT_PRODUCT_INFO),
                    "offer-b",
                    "25000002",
                    "26000002",
                    "additional",
                    1,
                    "공급사 A",
                    "[26000002] 열화상 센서",
                    20,
                    "https://shop.g2b.go.kr/b",
                    "2026-07-21T00:00:00+00:00",
                    1,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_catalog_lists_only_main_products_and_option_search_keeps_parent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "8TB 확장"})
        all_products = await client.get("/")

    assert response.status_code == 200
    assert response.text.count('data-main-product="') == 1
    assert 'data-main-product="25000001"' in response.text
    assert 'data-main-product="26000001"' not in response.text
    assert 'src="https://example.test/main.jpg"' in response.text
    assert 'data-parent-product-id="25000001"' in response.text
    assert 'class="catalog-detail-link"' in response.text
    assert 'href="/static/mvp.css?v=20260722-4"' in response.text
    assert 'data-main-product="26000001"' not in all_products.text


@pytest.mark.asyncio
async def test_catalog_search_matches_each_space_separated_term(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "공급사 A 영상감시장치"})

    assert response.status_code == 200
    assert 'data-main-product="25000001"' in response.text


@pytest.mark.asyncio
async def test_catalog_product_shows_embedded_product_attributes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET raw_json = ? WHERE product_id = ?",
            (
                '{"pdctAtrbNm":"01$x$x$x$용도$ATTR1|02$x$x$x$구성$ATTR2",'
                '"pdctAtrbCdDtlNm":"옥외감시$카메라:MODEL-A, 인젝터",'
                '"snymNm":"카메라:800만화소||인젝터:1Port/PoE"}',
                "25000001",
            ),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "25000001"})

    assert response.status_code == 200
    assert "상품 속성 정보" in response.text
    assert "카메라:800만화소" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["A 25000001", "25000001 A"])
async def test_catalog_search_term_order_is_irrelevant(
    tmp_path: Path,
    query: str,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": query})

    assert response.status_code == 200
    assert 'data-main-product="25000001"' in response.text


@pytest.mark.asyncio
async def test_option_can_start_a_new_estimate(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/catalog/products/25000001/options")

    assert response.status_code == 200
    assert 'action="/estimates/lines"' in response.text


@pytest.mark.asyncio
async def test_parent_option_endpoint_is_scoped_and_renders_empty_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        options = await client.get(
            "/catalog/products/25000001/options",
            params={"estimate_id": "draft-a"},
        )
        empty = await client.get("/catalog/products/25000003/options")
        fallback = await client.get("/", params={"q": "출입통제장치"})

    assert options.status_code == 200
    assert 'data-option-parent-id="25000001"' in options.text
    assert 'data-option-id="26000001"' in options.text
    assert "26000002" not in options.text
    assert 'name="relation_id" value="relation-a"' in options.text
    assert empty.status_code == 200
    assert 'data-empty-options="25000003"' in empty.text
    assert 'src="/static/product-placeholder.svg"' in fallback.text


@pytest.mark.asyncio
async def test_parent_options_are_loaded_in_thirty_row_chunks(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    with sqlite3.connect(database) as connection:
        _ = connection.executemany(
            """
            INSERT INTO verified_product_options VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    f"relation-{position}",
                    str(Operation.GET_MAS_CONTRACT_PRODUCT_INFO),
                    "offer-a",
                    "25000001",
                    f"27{position:06d}",
                    "additional",
                    position,
                    "공급사 A",
                    f"[{position}] 추가 옵션",
                    position,
                    "https://shop.g2b.go.kr/a",
                    "2026-07-21T00:00:00+00:00",
                    1,
                )
                for position in range(2, 32)
            ),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get("/catalog/products/25000001/options")
        second = await client.get(
            "/catalog/products/25000001/options", params={"page": 2}
        )

    assert first.text.count('class="catalog-option-card"') == 30
    assert first.headers["X-Catalog-Options-Next-Page"] == "2"
    assert "검증된 옵션 31건" in first.text
    assert second.text.count('class="catalog-option-card"') == 1
    assert second.headers["X-Catalog-Options-Next-Page"] == ""
    assert 'class="option-parent"' not in second.text


@pytest.mark.asyncio
async def test_option_column_fits_the_observed_desktop_width(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "8TB 확장"})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1003, "height": 912})
        await page.set_content(response.text)
        _ = await page.add_style_tag(path=MVP_CSS)
        metrics = cast(
            "_ViewportMetrics",
            await page.evaluate(
                """
                () => {
                  const workspace = document.querySelector('.catalog-workspace');
                  const panel = document.querySelector('.catalog-options-panel');
                  workspace.classList.add('has-options');
                  panel.hidden = false;
                  return {
                    documentWidth: document.documentElement.scrollWidth,
                    viewportWidth: window.innerWidth,
                    panelRight: panel.getBoundingClientRect().right,
                  };
                }
                """
            ),
        )
        await browser.close()

    assert metrics["documentWidth"] <= metrics["viewportWidth"]
    assert metrics["panelRight"] <= metrics["viewportWidth"]


@pytest.mark.asyncio
async def test_catalog_search_matches_equivalent_camera_spec_terms(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET spec = ? WHERE product_id = ?",
            ("보조카메라:화소:2MP/최대줌:Optical x4", "25000001"),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "200만화소 4배줌"})

    assert response.status_code == 200
    assert 'data-main-product="25000001"' in response.text
