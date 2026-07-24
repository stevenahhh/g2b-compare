from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from g2b_compare.priority_detail import parse_detail_options
from g2b_compare.priority_detail_crawl import group_targets
from g2b_compare.priority_models import ProductOptionRelation, ProductOptionTarget
from g2b_compare.priority_store import PriorityStore

if TYPE_CHECKING:
    from pathlib import Path


def test_parses_additional_and_component_relations() -> None:
    # Given: one row from each official detail-page dropdown.
    payload = {
        "dlCtrtOptnItmltL": [
            {
                "itemIdnfNo": "23563353",
                "ntslItemNm": "컴퓨터서버, 홍석, HS-C32",
                "prchsMthdSeNm": "별도구매",
                "dscntAplcnUprc": 3563000,
            },
            {
                "itemIdnfNo": "23527882",
                "ntslItemNm": "보안용카메라, 홍석, HS-D7522HIR",
                "prchsMthdSeNm": "선택부품",
                "dscntAplcnUprc": 1280000,
            },
        ]
    }

    # When: the public detail response is parsed.
    relations = parse_detail_options(payload)

    # Then: both dropdown kinds and their displayed prices are preserved.
    assert [(row.kind, row.product_id, row.price_won) for row in relations] == [
        ("additional", "23563353", 3563000),
        ("component", "23527882", 1280000),
    ]


def test_ignores_rows_that_are_not_existing_workbook_option_kinds() -> None:
    # Given: a non-option row in an otherwise valid response.
    payload = {
        "dlCtrtOptnItmltL": [
            {
                "itemIdnfNo": "25894957",
                "ntslItemNm": "영상감시장치",
                "prchsMthdSeNm": "본품",
                "dscntAplcnUprc": 428000,
            }
        ]
    }

    # When: the response is parsed.
    relations = parse_detail_options(payload)

    # Then: it cannot be mistaken for a child relation.
    assert relations == ()


def test_store_preserves_both_official_relation_kinds(tmp_path: Path) -> None:
    # Given: one collected main product and both kinds of official child row.
    database = tmp_path / "relations.sqlite3"
    store = PriorityStore(database)
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            """
            INSERT INTO priority_products (
                product_id, operation, contract_number, contract_sequence,
                category_number, category_name, detail_category_number, spec,
                company_name, unit, price_won, contract_method,
                delivery_condition, delivery_days, contract_end_date, image_url,
                detail_url, raw_json, observed_at
            ) VALUES (?, ?, ?, ?, '', '', '', '', ?, '', 0, '', '', '', '',
                      '', ?, '{}', '')
            """,
            (
                "25894957",
                "site",
                "002270042_1270002360",
                "2360",
                "주식회사 홍석",
                "https://shop.g2b.go.kr/detail",
            ),
        )
    relations = (
        ProductOptionRelation(
            kind="additional",
            product_id="23563353",
            raw_label="[별도구매] [23563353] 컴퓨터서버 : 3,563,000",
            price_won=3563000,
        ),
        ProductOptionRelation(
            kind="component",
            product_id="23527882",
            raw_label="[선택부품] [23527882] 보안용카메라 : 1,280,000",
            price_won=1280000,
        ),
    )

    # When: the parent relation result is saved.
    store.save_site_result("25894957", relations, status="complete")

    # Then: the UI-facing verified table keeps the two distinct kinds.
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT relation_kind, option_product_id FROM verified_product_options
            ORDER BY position
            """
        ).fetchall()
    assert rows == [("additional", "23563353"), ("component", "23527882")]


def test_contract_group_relations_apply_to_every_main_product(tmp_path: Path) -> None:
    # Given: two main products belonging to the same official contract group.
    database = tmp_path / "group-relations.sqlite3"
    store = PriorityStore(database)
    with sqlite3.connect(database) as connection:
        _ = connection.executemany(
            """
            INSERT INTO priority_products (
                product_id, operation, contract_number, contract_sequence,
                category_number, category_name, detail_category_number, spec,
                company_name, unit, price_won, contract_method,
                delivery_condition, delivery_days, contract_end_date, image_url,
                detail_url, raw_json, observed_at
            ) VALUES (?, 'site', ?, ?, '', '', '', '', ?, '', 0, '', '', '', '',
                      '', ?, ?, '')
            """,
            (
                (
                    "25894957",
                    "002270042_1270002360",
                    "2360",
                    "주식회사 홍석",
                    "https://shop.g2b.go.kr/detail-a",
                    '{"ctrtItemMngNo":"002270042_1270002360",'
                    '"ctrtNo":"002270042_1","ctrtChgOrd":"27"}',
                ),
                (
                    "24092093",
                    "002270042_1270000005",
                    "5",
                    "주식회사 홍석",
                    "https://shop.g2b.go.kr/detail-b",
                    '{"ctrtItemMngNo":"002270042_1270000005",'
                    '"ctrtNo":"002270042_1","ctrtChgOrd":"27"}',
                ),
            ),
        )
    targets = store.pending_site_targets(0)
    relation = ProductOptionRelation(
        kind="component",
        product_id="23527882",
        raw_label="[선택부품] [23527882] 보안용카메라 : 1,280,000",
        price_won=1280000,
    )

    # When: one shared contract response is persisted for the whole group.
    store.save_contract_group_result(targets, (relation,), status="complete")

    # Then: either main product resolves the same verified child without duplicates.
    assert [row.product_id for row in store.list_catalog_options("25894957")] == [
        "23527882"
    ]
    assert [row.product_id for row in store.list_catalog_options("24092093")] == [
        "23527882"
    ]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM priority_contract_options"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM priority_product_contract_groups"
        ).fetchone() == (2,)
    assert all(isinstance(target, ProductOptionTarget) for target in targets)


def test_groups_all_main_products_by_official_contract() -> None:
    # Given: two products sharing one contract and one from another contract.
    targets = (
        ProductOptionTarget(
            product_id="25894957",
            contract_item_number="002270042_1270002360",
            contract_group="002270042_1:27",
        ),
        ProductOptionTarget(
            product_id="24092093",
            contract_item_number="002270042_1270000005",
            contract_group="002270042_1:27",
        ),
        ProductOptionTarget(
            product_id="25110164",
            contract_item_number="0023H0530_1000000004",
            contract_group="0023H0530_1:0",
        ),
    )

    # When: the full crawl target list is grouped.
    groups = group_targets(targets)

    # Then: one official request can cover every product in each contract.
    assert [len(group) for group in groups] == [2, 1]
