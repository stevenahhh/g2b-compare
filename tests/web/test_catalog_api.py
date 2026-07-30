from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from g2b_compare.web import catalog_api
from g2b_compare.web.app import create_app
from g2b_compare.web.catalog_api import build_catalog_api_router

from .test_catalog_hierarchy import _seed_hierarchy


@pytest.mark.asyncio
async def test_baseline_combined_company_and_item_search_legacy_route(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", params={"q": "25000001 A"})
    assert response.status_code == 200
    assert 'data-main-product="25000001"' in response.text


@pytest.mark.asyncio
async def test_baseline_option_pagination_legacy_route(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = create_app(database=database, home=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get("/catalog/products/25000001/options")
        second = await client.get(
            "/catalog/products/25000001/options", params={"page": 2}
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert 'data-option-id="26000001"' in first.text
    assert second.headers["X-Catalog-Options-Next-Page"] == ""


def _api_app(database: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(build_catalog_api_router(database))
    return app


def _seed_api_fixture(database: Path) -> None:
    _seed_hierarchy(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET category_name = ?, company_name = ?, raw_json = ? WHERE product_id = ?",
            (
                "코리아넷 영상감시장치",
                "코리아넷",
                '{"pdctAtrbNm":"01$x$x$Resolution$x|02$x$x$Sensor$x","pdctAtrbCdDtlNm":"4K$CMOS"}',
                "25000001",
            ),
        )
        connection.execute(
            "INSERT INTO verified_product_options VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "relation-c", "GET_MAS_CONTRACT_PRODUCT_INFO", "offer-c", "25000001",
                "26000002", "component", 2, "코리아넷", "[26000002] 두번째 옵션", 20,
                "https://shop.g2b.go.kr/c", "2026-07-21T00:00:00+00:00", 1,
            ),
        )


def _seed_document_catalog_fixture(database: Path) -> None:
    _seed_api_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE verified_product_options
            SET company_name = ?
            WHERE relation_id = ?
            """,
            ("코리아넷", "relation-a"),
        )
        connection.execute(
            """
            INSERT INTO priority_options
            (source_row, company_name, option_kind, product_id, item_name, spec, price_won, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                "코리아넷",
                "추가선택품목",
                "26000001",
                "저장장치 옵션",
                "8TB 확장",
                10,
                "",
            ),
        )


@pytest.mark.asyncio
async def test_catalog_products_json_contract_and_combined_search(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_api_fixture(database)
    app = _api_app(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/catalog/products", params={"q": "코리아넷 영상감시장치", "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert set(("items", "page", "page_count", "total_count")) <= body.keys()
    assert [item["product_id"] for item in body["items"]] == ["25000001"]
    assert set(body["items"][0]) == {"product_id", "name", "spec", "unit", "price_won", "company_name", "contract_method", "delivery_condition", "delivery_days", "contract_end_date", "detail_url", "g2b_url", "image_url", "attributes"}
    assert body["items"][0]["image_url"] == "https://example.test/main.jpg"
    assert body["items"][0]["attributes"] == [
        {"name": "Resolution", "value": "4K", "unit": ""},
        {"name": "Sensor", "value": "CMOS", "unit": ""},
    ]


@pytest.mark.asyncio
async def test_catalog_products_can_prioritize_company_without_filtering_others(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_api_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET price_won = ? WHERE product_id = ?",
            (2_000_000, "25000001"),
        )
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/catalog/products",
            params={
                "preferred_company_name": "코리아넷",
                "sort": "price_asc",
                "page_size": 2,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert body["items"][0]["company_name"] == "코리아넷"
    assert body["items"][1]["company_name"] == "공급사 A"


@pytest.mark.asyncio
async def test_catalog_options_json_has_relation_and_parent_and_pagination(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_api_fixture(database)
    app = _api_app(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/catalog/products/25000001/options", params={"page": 1, "page_size": 1})
        second = await client.get("/api/catalog/products/25000001/options", params={"page": 2, "page_size": 1})
        components = await client.get("/api/catalog/products/25000001/options", params={"relation_kind": "component"})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_count"] == 2
    assert body["total_count"] == 2
    assert second.json()["page"] == 2
    assert second.json()["page_count"] == 2
    assert second.json()["total_count"] == 2
    option = body["items"][0]
    assert option["parent_product_id"] == "25000001"
    assert option["relation_id"] == "relation-a"
    assert set(option) == {
        "parent_product_id",
        "parent_name",
        "relation_id",
        "relation_kind",
        "product_id",
        "name",
        "spec",
        "unit",
        "price_won",
        "company_name",
        "detail_url",
        "g2b_url",
        "image_url",
        "attributes",
    }
    assert option["relation_kind"] == "additional"
    assert option["image_url"] == "https://example.test/option.jpg"
    assert option["attributes"] == []
    assert second.json()["items"][0]["relation_kind"] == "component"
    assert components.json()["total_count"] == 1
    assert components.json()["items"][0]["relation_kind"] == "component"


@pytest.mark.asyncio
async def test_document_catalog_includes_company_main_products_and_both_option_kinds(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_document_catalog_fixture(database)
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/catalog/document-products",
            params={"company_name": "코리아넷", "page_size": 500},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert {item.get("relation_kind", "main") for item in body["items"]} == {
        "main",
        "additional",
        "component",
    }
    options = [item for item in body["items"] if "relation_kind" in item]
    assert {item["parent_product_id"] for item in options} == {"25000001"}
    assert {item["parent_name"] for item in options} == {"코리아넷 영상감시장치"}
    assert {item["relation_id"] for item in options} == {"relation-a", "relation-c"}


@pytest.mark.asyncio
async def test_koreanet_catalog_filters_mains_and_splits_relation_search(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_document_catalog_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO verified_product_options VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "relation-d",
                "GET_MAS_CONTRACT_PRODUCT_INFO",
                "offer-d",
                "25000001",
                "26000002",
                "additional",
                3,
                "코리아넷",
                "[26000002] 정보통신공사, 종합시험 : 100",
                100,
                "https://example.test/construction",
                "2026-07-21T00:00:00+00:00",
                1,
            ),
        )
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mains = await client.get(
            "/api/catalog/products",
            params={"company_name": "코리아넷", "page_size": 100},
        )
        selection = await client.get(
            "/api/catalog/relations",
            params={
                "company_name": "코리아넷",
                "category": "selection",
                "page_size": 100,
            },
        )
        construction = await client.get(
            "/api/catalog/relations",
            params={
                "company_name": "코리아넷",
                "category": "construction",
                "q": "정보통신공사",
                "page_size": 100,
            },
        )

    assert mains.status_code == 200
    assert mains.json()["total_count"] == 1
    assert selection.json()["total_count"] == 1
    assert construction.json()["total_count"] == 1
    assert construction.json()["items"][0]["parent_product_id"] == "25000001"
    assert construction.json()["items"][0]["parent_name"] == "코리아넷 영상감시장치"


@pytest.mark.asyncio
async def test_document_catalog_search_matches_option_without_returning_parent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_document_catalog_fixture(database)
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/catalog/document-products",
            params={"company_name": "코리아넷", "q": "8TB 확장", "page_size": 500},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["relation_kind"] == "additional"
    assert body["items"][0]["product_id"] == "26000001"


@pytest.mark.asyncio
async def test_document_catalog_search_matches_equivalent_spec_terms(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_document_catalog_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET spec = ? WHERE product_id = ?",
            ("보조카메라:화소:2MP/최대줌:Optical x4", "25000001"),
        )
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/catalog/document-products",
            params={
                "company_name": "코리아넷",
                "q": "200만화소 4배줌",
                "page_size": 500,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["product_id"] == "25000001"


@pytest.mark.asyncio
async def test_document_catalog_reuses_company_snapshot_between_search_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_document_catalog_fixture(database)
    option_reads = 0
    original = catalog_api.list_catalog_options_for_company

    def counted_options(
        path: Path,
        company_name: str,
    ) -> tuple[catalog_api.CatalogOption, ...]:
        nonlocal option_reads
        option_reads += 1
        return original(path, company_name)

    monkeypatch.setattr(
        catalog_api,
        "list_catalog_options_for_company",
        counted_options,
    )
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get(
            "/api/catalog/document-products",
            params={"company_name": "코리아넷", "q": "영상감시장치"},
        )
        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
                ("a" * 32, "Document write", "b" * 64, "now", "now"),
            )
        second = await client.get(
            "/api/catalog/document-products",
            params={"company_name": "코리아넷", "q": "8TB"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert option_reads == 1


@pytest.mark.asyncio
async def test_document_catalog_returns_contract_option_once_per_relation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_api_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO priority_product_contract_groups
            (product_id, contract_group)
            VALUES (?, ?)
            """,
            (("25000001", "group-a"), ("25000002", "group-a")),
        )
        connection.execute(
            """
            INSERT INTO priority_contract_options
            (contract_group, relation_id, option_product_id, relation_kind,
             position, company_name, raw_label, relation_price_won,
             observed_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "group-a",
                "contract-relation-a",
                "26000001",
                "additional",
                1,
                "코리아넷",
                "[별도구매] [26000001] 정보통신공사, 종합시험 : 109,760",
                10,
                "2026-07-21T00:00:00+00:00",
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO priority_options
            (source_row, company_name, option_kind, product_id, item_name, spec,
             price_won, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99,
                "코리아넷",
                "추가선택품목",
                "26000001",
                "정보통신공사",
                "영상감시장치, WRONG-PARENT-SPEC",
                10,
                "",
            ),
        )
    app = _api_app(database)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/catalog/document-products",
            params={
                "company_name": "코리아넷",
                "q": "정보통신공사",
                "page_size": 500,
            },
        )

    assert response.status_code == 200
    options = [
        item for item in response.json()["items"] if "relation_kind" in item
    ]
    assert len(options) == 1
    assert options[0]["relation_id"] == "contract-relation-a"
    assert options[0]["parent_product_id"] == "25000001"
    assert options[0]["name"] == "정보통신공사"
    assert options[0]["spec"] == "종합시험"


@pytest.mark.asyncio
async def test_catalog_api_rejects_invalid_sort_and_unknown_parent(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_hierarchy(database)
    app = _api_app(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.get("/api/catalog/products", params={"sort": "bogus"})
        unknown = await client.get("/api/catalog/products/missing/options")
    assert invalid.status_code == 422
    assert unknown.status_code == 404
