"""Workbook-grounded comparison bundle contracts."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import as_int, query
from g2b_compare.priority_store import PriorityStore
from g2b_compare.services import EstimateLineInput, EstimateStore
from g2b_compare.web.estimate_selection import (
    comparison_views,
    seed_document_comparisons_in_transaction,
)

if TYPE_CHECKING:
    from pathlib import Path

type OptionSeed = tuple[str, str, str, str, str, int, str]


def _seed_product(
    database: Path,
    product_id: str,
    company: str,
    price: int,
) -> None:
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            """
            INSERT INTO priority_products
            (product_id, operation, contract_number, contract_sequence,
            category_number, category_name, detail_category_number, spec,
            company_name, unit, price_won, contract_method, delivery_condition,
            delivery_days, contract_end_date, image_url, detail_url, raw_json,
            observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?)
            """,
            (
                product_id,
                "getMASCntrctPrdctInfoList",
                f"contract-{product_id}",
                "1",
                "46171622",
                "영상감시장치",
                "4617162201",
                f"영상감시장치, {company}, 방범감시시스템",
                company,
                "조",
                price,
                "다수공급자계약",
                "현장설치도",
                "60",
                "20271231",
                "",
                "https://shop.g2b.go.kr/detail",
                "{}",
                "2026-07-31T00:00:00+00:00",
            ),
        )


def _seed_option(
    database: Path,
    option: OptionSeed,
) -> None:
    parent_id, group, relation_id, product_id, company, price, spec = option
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            "INSERT OR IGNORE INTO priority_product_contract_groups VALUES (?, ?)",
            (parent_id, group),
        )
        position_row = query(
            connection,
            """
            SELECT COALESCE(MAX(position), 0) + 1
            FROM priority_contract_options WHERE contract_group = ?
            """,
            (group,),
        ).fetchone()
        assert position_row is not None
        position = as_int(position_row[0])
        _ = connection.execute(
            """
            INSERT INTO priority_contract_options VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group,
                relation_id,
                product_id,
                "additional",
                position,
                company,
                f"[{product_id}] 하드디스크드라이브, {spec}",
                price,
                "2026-07-31T00:00:00+00:00",
                1,
            ),
        )


def _main_input(product_id: str, company: str, price: int) -> EstimateLineInput:
    return EstimateLineInput(
        "main",
        product_id,
        None,
        None,
        "getMASCntrctPrdctInfoList",
        f"offer-{product_id}",
        "영상감시장치",
        f"영상감시장치, {company}, 방범감시시스템",
        company,
        "조",
        price,
        Decimal(1),
    )


def _option_input(
    product_id: str,
    parent_id: str,
    relation_id: str,
    company: str,
    spec: str = "8TB",
) -> EstimateLineInput:
    return EstimateLineInput(
        "option",
        product_id,
        parent_id,
        relation_id,
        None,
        None,
        "하드디스크드라이브",
        spec,
        company,
        "개",
        100,
        Decimal(1),
    )


def test_selected_bundle_is_a_and_alternatives_use_bundle_totals(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _ = PriorityStore(database)
    migrate(database)
    products = (
        ("26000001", "선택사", 100),
        ("26000002", "B사", 105),
        ("26000003", "B사", 120),
        ("26000004", "C사", 150),
    )
    for product_id, company, price in products:
        _seed_product(database, product_id, company, price)
    options = (
        ("26000001", "group-a", "relation-a", "27000001", "선택사", 100, "8TB"),
        ("26000001", "group-a", "relation-a2", "27000011", "선택사", 100, "10TB"),
        ("26000002", "group-b1", "relation-b1", "27000002", "B사", 400, "8TB"),
        ("26000002", "group-b1", "relation-b12", "27000012", "B사", 100, "10TB"),
        ("26000003", "group-b2", "relation-b2", "27000003", "B사", 100, "8TB"),
        ("26000004", "group-c", "relation-c", "27000004", "C사", 100, "8TB"),
        ("26000004", "group-c", "relation-c2", "27000014", "C사", 100, "10TB"),
    )
    for option in options:
        _seed_option(database, option)
    store = EstimateStore(database)
    main_id = "a" * 32
    option_id = "b" * 32
    second_option_id = "d" * 32

    draft = store.replace_draft(
        "c" * 32,
        "workbook bundle",
        "0" * 64,
        (
            (main_id, _main_input("26000001", "선택사", 100)),
            (
                option_id,
                _option_input(
                    "27000001",
                    "26000001",
                    "relation-a",
                    "선택사",
                ),
            ),
            (
                second_option_id,
                _option_input(
                    "27000011",
                    "26000001",
                    "relation-a2",
                    "선택사",
                    "10TB",
                ),
            ),
        ),
        seed_document_comparisons_in_transaction,
    )

    comparisons = comparison_views(database, draft)

    assert [item.product_id for item in comparisons[main_id]] == [
        "26000001",
        "26000003",
        "26000004",
    ]
    assert [item.price_won for item in comparisons[main_id]] == [100, 120, 150]
    assert [item.product_id for item in comparisons[option_id]] == [
        "27000001",
        "27000003",
        "27000004",
    ]
    assert [item.price_won for item in comparisons[option_id]] == [100, 100, 100]
    assert [item.product_id for item in comparisons[second_option_id]] == [
        "27000011",
        "27000012",
        "27000014",
    ]
    assert [
        main.price_won + option.price_won
        for main, option in zip(
            comparisons[main_id],
            comparisons[option_id],
            strict=True,
        )
    ] == [200, 220, 250]
