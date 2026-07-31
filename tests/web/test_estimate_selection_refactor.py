"""Stable facade and persistence contracts for estimate selection."""

from __future__ import annotations

import inspect
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.db.migrate import migrate
from g2b_compare.priority_store import PriorityStore
from g2b_compare.services import EstimateLineInput, EstimateStore
from g2b_compare.web import (
    estimate_resolution,
    estimate_seeding,
    estimate_selection,
    estimate_views,
)

if TYPE_CHECKING:
    from pathlib import Path


def _seed_candidates(database: Path) -> None:
    _ = PriorityStore(database)
    migrate(database)
    for product_id, company, price in (
        ("25454886", "주식회사 코리아넷", 1_000),
        ("25454887", "B사", 1_050),
        ("25454888", "C사", 1_100),
    ):
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
                    "0023H000001",
                    "1",
                    "46171622",
                    "영상감시장치",
                    "4617162201",
                    "영상감시장치, CAMERA, 방범감시시스템",
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
                    "2026-07-21T00:00:00+00:00",
                ),
            )


def _line_input() -> EstimateLineInput:
    return EstimateLineInput(
        "main",
        "25454886",
        None,
        None,
        "operation",
        "offer-a",
        "영상감시장치",
        "영상감시장치, CAMERA, 방범감시시스템",
        "주식회사 코리아넷",
        "조",
        1_000,
        Decimal(1),
    )


def test_estimate_selection_facade_has_stable_public_exports() -> None:
    assert estimate_selection.__all__ == [
        "COMPARISON_SLOT_COUNT",
        "ComparisonView",
        "comparison_views",
        "resolve_selection",
        "seed_comparisons",
        "seed_comparisons_in_transaction",
        "seed_document_comparisons_in_transaction",
    ]
    assert estimate_selection.resolve_selection is estimate_resolution.resolve_selection
    assert (
        estimate_selection.seed_comparisons_in_transaction
        is estimate_seeding.seed_comparisons_in_transaction
    )
    assert estimate_selection.comparison_views is estimate_views.comparison_views
    assert tuple(
        inspect.signature(estimate_selection.resolve_selection).parameters
    ) == (
        "database",
        "product_id",
        "parent_product_id",
        "relation_id",
        "quantity",
    )
    assert tuple(
        inspect.signature(
            estimate_selection.seed_document_comparisons_in_transaction
        ).parameters
    ) == ("connection", "lines")


def test_document_seeding_repairs_invalid_records_for_readback(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_candidates(database)
    store = EstimateStore(database)
    line_id = "a" * 32
    draft = store.replace_draft(
        "b" * 32,
        "comparison persistence",
        "0" * 64,
        ((line_id, _line_input()),),
        estimate_selection.seed_document_comparisons_in_transaction,
    )

    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            """
            DELETE FROM estimate_comparisons
            WHERE estimate_line_id = ? AND slot = 'C'
            """,
            (line_id,),
        )
    repaired = store.replace_draft(
        draft.id,
        draft.title,
        draft.template_sha256,
        ((line_id, _line_input()),),
        estimate_selection.seed_document_comparisons_in_transaction,
    )

    comparisons = estimate_selection.comparison_views(database, repaired)

    assert [item.slot for item in comparisons[line_id]] == ["A", "B", "C"]
    assert [item.product_id for item in comparisons[line_id]] == [
        "25454886",
        "25454887",
        "25454888",
    ]
