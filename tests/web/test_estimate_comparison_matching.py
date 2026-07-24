# ruff: noqa: E501
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI

from g2b_compare.web.estimate_api import build_estimate_api_router
from g2b_compare.web.estimate_selection import resolve_selection

from .test_estimate_routes import _seed_product

if TYPE_CHECKING:
    from pathlib import Path


def _product(
    database: Path,
    product_id: str,
    company: str,
    price: int,
    components: str,
) -> None:
    _seed_product(
        database,
        product_id,
        company_name=company,
        price_won=price,
        spec=f"\uc601\uc0c1\uac10\uc2dc\uc7a5\uce58, {company}, MODEL, \ubc29\ubc94\uac10\uc2dc\uc2dc\uc2a4\ud15c",
    )
    raw = {
        "pdctAtrbCdDtlNm": f"\ubc29\ubc94\uac10\uc2dc\uc2dc\uc2a4\ud15c${components}",
        "snymNm": "\ubc29\ubc94\uac10\uc2dc\uc2dc\uc2a4\ud15c||\uce74\uba54\ub77c:200\ub9cc\ud654\uc18c/\uad11\ud5594\ubc30\uc90c",
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET raw_json = ? WHERE product_id = ?",
            (json.dumps(raw, ensure_ascii=False), product_id),
        )


def _seed_comparison_fixture(database: Path) -> None:
    products = (
        ("11111111", "주식회사 코리아넷", 1_000, "\uce74\uba54\ub77c"),
        ("11111112", "D\uc0ac", 1_001, "\uce74\uba54\ub77c, \uc778\ud130\ucf64"),
        ("11111113", "E\uc0ac", 1_002, "\uce74\uba54\ub77c, \uae08\uc18d\uae30\ub465"),
        (
            "11111114",
            "B\uc0ac",
            1_100,
            "\uce74\uba54\ub77c, \ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
        ),
        (
            "11111115",
            "C\uc0ac",
            1_200,
            "\uce74\uba54\ub77c, \ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
        ),
    )
    for product_id, company, price, components in products:
        _product(database, product_id, company, price, components)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO priority_companies VALUES (?, ?, '', '', 1, '')",
            ((company, index) for index, (_, company, _, _) in enumerate(products, 1)),
        )
        connection.executemany(
            "INSERT INTO priority_product_contract_groups VALUES (?, ?)",
            (("11111114", "group-b"), ("11111115", "group-c")),
        )
        connection.executemany(
            "INSERT INTO priority_contract_options VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "group-b",
                    "relation-b",
                    "22222222",
                    "additional",
                    1,
                    "B\uc0ac",
                    "[\ubcc4\ub3c4\uad6c\ub9e4] [22222222] \ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58, B-8P, 8port PoE : 110",
                    110,
                    "2026-07-22T00:00:00+00:00",
                    1,
                ),
                (
                    "group-c",
                    "relation-c",
                    "22222222",
                    "additional",
                    1,
                    "C\uc0ac",
                    "[\ubcc4\ub3c4\uad6c\ub9e4] [22222222] \ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58, C-8P, 8port PoE : 120",
                    120,
                    "2026-07-22T00:00:00+00:00",
                    1,
                ),
            ),
        )
        connection.executemany(
            "INSERT INTO priority_options VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    1,
                    "B\uc0ac",
                    "\ucd94\uac00\uc120\ud0dd\ud488\ubaa9",
                    "22222222",
                    "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
                    "B-8P, 8port PoE",
                    110,
                    "",
                ),
                (
                    2,
                    "C\uc0ac",
                    "\ucd94\uac00\uc120\ud0dd\ud488\ubaa9",
                    "22222222",
                    "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
                    "C-8P, 8port PoE",
                    120,
                    "",
                ),
            ),
        )


def _seed_shared_option_relations(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO priority_contract_options VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "shared-b",
                    "shared-relation-b",
                    "33333333",
                    "additional",
                    1,
                    "B사",
                    "[별도구매] [33333333] UTP케이블, CAT.5E/CM 4P : 2,740",
                    2_740,
                    "2026-07-22T00:00:00+00:00",
                    1,
                ),
                (
                    "shared-c",
                    "shared-relation-c",
                    "33333333",
                    "additional",
                    1,
                    "C사",
                    "[별도구매] [33333333] UTP케이블, CAT.5E/CM 4P : 2,740",
                    2_740,
                    "2026-07-22T00:00:00+00:00",
                    1,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_document_components_and_contract_options_drive_comparisons(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_comparison_fixture(database)
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    payload = {
        "title": "comparison fixture",
        "lines": [
            {
                "id": "a" * 32,
                "line_kind": "main",
                "product_id": "11111111",
                "parent_product_id": None,
                "relation_id": None,
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "\uc601\uc0c1\uac10\uc2dc\uc7a5\uce58",
                "spec_snapshot": "\uc601\uc0c1\uac10\uc2dc\uc7a5\uce58, 코리아넷, MODEL, \ubc29\ubc94\uac10\uc2dc\uc2dc\uc2a4\ud15c",
                "company_snapshot": "주식회사 코리아넷",
                "unit_snapshot": "\uc870",
                "unit_price_won_snapshot": 1_000,
                "quantity": "1",
            },
            {
                "id": "b" * 32,
                "line_kind": "option",
                "product_id": "22222221",
                "parent_product_id": "11111111",
                "relation_id": "relation-a",
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
                "spec_snapshot": "A-8P, 8port PoE",
                "company_snapshot": "주식회사 코리아넷",
                "unit_snapshot": "\ub300",
                "unit_price_won_snapshot": 100,
                "quantity": "1",
            },
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'f' * 32}", json=payload)

    assert response.status_code == 200
    lines = response.json()["lines"]
    assert [item["product_id"] for item in lines[0]["comparisons"]] == [
        "11111111",
        "11111114",
        "11111115",
    ]
    option_product_ids = [item["product_id"] for item in lines[1]["comparisons"]]
    assert option_product_ids == [
        "22222221",
        "22222222",
        "22222222",
    ]
    assert [item["company_snapshot"] for item in lines[1]["comparisons"]] == [
        "주식회사 코리아넷",
        "B\uc0ac",
        "C\uc0ac",
    ]


@pytest.mark.asyncio
async def test_standalone_option_compares_with_equivalent_options(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_comparison_fixture(database)
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    payload = {
        "title": "standalone option",
        "lines": [
            {
                "id": "b" * 32,
                "line_kind": "option",
                "product_id": "22222221",
                "parent_product_id": "11111111",
                "relation_id": "relation-a",
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
                "spec_snapshot": "A-8P, 8port PoE",
                "company_snapshot": "주식회사 코리아넷",
                "unit_snapshot": "\ub300",
                "unit_price_won_snapshot": 100,
                "quantity": "1",
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'d' * 32}", json=payload)

    assert response.status_code == 200
    comparisons = response.json()["lines"][0]["comparisons"]
    product_ids = [item["product_id"] for item in comparisons]
    assert product_ids == [
        "22222221",
        "22222222",
        "22222222",
    ]
    assert [item["company_snapshot"] for item in comparisons] == [
        "주식회사 코리아넷",
        "B\uc0ac",
        "C\uc0ac",
    ]


@pytest.mark.asyncio
async def test_third_party_8port_option_requires_distinct_product_ids(
    tmp_path: Path,
) -> None:
    # Given: an 8-port option whose parent is a third-party unit-price contract.
    database = tmp_path / "g2b.sqlite3"
    _seed_comparison_fixture(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE priority_products SET contract_method = '제3자단가계약'
            WHERE product_id = '11111111'
            """
        )
        connection.execute(
            """
            UPDATE priority_products SET price_won = 10000
            WHERE product_id IN ('11111114', '11111115')
            """
        )
        connection.execute(
            """
            INSERT INTO priority_contract_options VALUES (
                'group-c', 'relation-c-distinct', '22222223', 'additional', 2,
                'C사',
                '[별도구매] [22222223] 네트워크스위치, C-8P, 8port PoE : 120',
                120, '2026-07-22T00:00:00+00:00', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO priority_options VALUES (
                3, 'C사', '추가선택품목', '22222223', '네트워크스위치',
                'C-8P, 8port PoE', 120, ''
            )
            """
        )
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    payload = {
        "title": "third-party option",
        "lines": [
            {
                "id": "9" * 32,
                "line_kind": "option",
                "product_id": "22222221",
                "parent_product_id": "11111111",
                "relation_id": "relation-a",
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58",
                "spec_snapshot": "A-8P, 8port PoE",
                "company_snapshot": "주식회사 코리아넷",
                "unit_snapshot": "\ub300",
                "unit_price_won_snapshot": 100,
                "quantity": "1",
            }
        ],
    }

    # When: one save seeds the comparison companies.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'9' * 32}", json=payload)

    # Then: third-party options use three different product identifiers.
    assert response.status_code == 200
    comparisons = response.json()["lines"][0]["comparisons"]
    assert [item["product_id"] for item in comparisons] == [
        "22222221",
        "22222222",
        "22222223",
    ]
    assert [item["company_snapshot"] for item in comparisons] == [
        "주식회사 코리아넷",
        "B\uc0ac",
        "C\uc0ac",
    ]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM estimate_comparisons "
            "WHERE estimate_line_id = ? AND slot <> 'A'",
            ("9" * 32,),
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'9' * 32}", json=payload)
    assert len(response.json()["lines"][0]["comparisons"]) == 3


@pytest.mark.asyncio
async def test_shared_contract_option_relations_fill_distinct_companies(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_comparison_fixture(database)
    _seed_shared_option_relations(database)
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    payload = {
        "title": "shared option",
        "lines": [
            {
                "id": "c" * 32,
                "line_kind": "option",
                "product_id": "33333333",
                "parent_product_id": "11111111",
                "relation_id": "shared-relation-a",
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "UTP케이블",
                "spec_snapshot": "CAT.5E/CM 4P",
                "company_snapshot": "주식회사 코리아넷",
                "unit_snapshot": "개",
                "unit_price_won_snapshot": 2_740,
                "quantity": "1",
            }
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'c' * 32}", json=payload)

    assert response.status_code == 200
    comparisons = response.json()["lines"][0]["comparisons"]
    assert [item["company_snapshot"] for item in comparisons] == [
        "주식회사 코리아넷",
        "B사",
        "C사",
    ]
    assert all(item["product_id"] == "33333333" for item in comparisons)
    assert all(item["price_won_snapshot"] == 2_740 for item in comparisons)


@pytest.mark.asyncio
async def test_koreanet_is_baseline_and_other_companies_are_not_cheaper(
    tmp_path: Path,
) -> None:
    # Given: a non-Koreanet selection and same-category candidates around its price.
    database = tmp_path / "g2b.sqlite3"
    products = (
        ("11111111", "선택사", 900),
        ("11111112", "주식회사 코리아넷", 1_000),
        ("11111113", "저가사", 800),
        ("11111114", "동가사", 1_000),
        ("11111116", "상한사", 2_100),
        ("11111115", "급등사", 4_600),
    )
    for product_id, company, price in products:
        _product(database, product_id, company, price, "카메라")
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    payload = {
        "title": "Koreanet baseline",
        "lines": [
            {
                "id": "a" * 32,
                "line_kind": "main",
                "product_id": "11111111",
                "parent_product_id": None,
                "relation_id": None,
                "offer_operation": "operation",
                "offer_key": "offer-a",
                "item_name_snapshot": "영상감시장치",
                "spec_snapshot": "영상감시장치, 선택사, MODEL, 방범감시시스템",
                "company_snapshot": "선택사",
                "unit_snapshot": "조",
                "unit_price_won_snapshot": 900,
                "quantity": "1",
            }
        ],
    }

    # When: the web API persists and seeds the estimate comparisons.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(f"/api/estimates/{'e' * 32}", json=payload)

    # Then: Koreanet is A and every distinct-company comparison costs at least A.
    assert response.status_code == 200
    comparisons = response.json()["lines"][0]["comparisons"]
    assert comparisons[0]["company_snapshot"] == "주식회사 코리아넷"
    assert {item["company_snapshot"] for item in comparisons[1:]} == {
        "동가사",
        "상한사",
    }
    baseline_price = comparisons[0]["price_won_snapshot"]
    assert baseline_price == 1_000
    assert all(
        baseline_price <= item["price_won_snapshot"] <= baseline_price * 2.1
        for item in comparisons[1:]
    )


def test_option_selection_prefers_relation_label_over_product_spec(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(
        database,
        "11111111",
        company_name="주식회사 코리아넷",
        spec="영상감시장치, 코리아넷, PARENT, 방범감시시스템",
    )
    _seed_product(
        database,
        "33333333",
        company_name="주식회사 코리아넷",
        spec="영상감시장치, 코리아넷, WRONG, 방범감시시스템",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_product_contract_groups VALUES (?, ?)",
            ("11111111", "group-a"),
        )
        connection.execute(
            "INSERT INTO priority_contract_options VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "group-a",
                "relation-a",
                "33333333",
                "additional",
                1,
                "주식회사 코리아넷",
                "[별도구매] [33333333] UTP케이블, CAT.5E/CM 4P : 2,740",
                2_740,
                "2026-07-22T00:00:00+00:00",
                1,
            ),
        )

    line = resolve_selection(
        database,
        "33333333",
        "11111111",
        "relation-a",
        Decimal(1),
    )

    assert line.item_name_snapshot == "UTP케이블"
    assert line.spec_snapshot == "CAT.5E/CM 4P"
