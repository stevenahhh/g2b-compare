"""Characterize the stable estimate-store facade and extracted seams."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from g2b_compare import services
from g2b_compare.db.sql import SqlRow, as_int, query
from g2b_compare.services.estimate_store_records import document_line, line_from_row

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.services.estimate_models import EstimateLine


RESEED_FAILURE = "forced reseed failure"


def _item(
    product_id: str = "25454886",
    *,
    quantity: Decimal | None = None,
) -> services.EstimateLineInput:
    return services.EstimateLineInput(
        line_kind="main",
        product_id=product_id,
        parent_product_id=None,
        relation_id=None,
        offer_operation="getMASCntrctPrdctInfoList",
        offer_key=f"offer-{product_id}",
        item_name_snapshot="영상감시장치",
        spec_snapshot="800만화소",
        company_snapshot="공급사",
        unit_snapshot="조",
        unit_price_won_snapshot=100,
        quantity=quantity if quantity is not None else Decimal(1),
    )


def test_row_mapping_round_trips_optional_snapshots_and_decimal_quantity() -> None:
    """The extracted mapper retains every persisted snapshot field exactly."""
    row: SqlRow = (
        "line-1",
        2,
        "option",
        "25560063",
        "25454886",
        "relation-1",
        "getMASCntrctPrdctInfoList",
        "offer-parent",
        "저장장치",
        "8TB",
        "관계 공급사",
        "개",
        5_431_000,
        "2.75",
    )

    line = line_from_row(row)

    assert line == document_line(
        "line-1",
        2,
        services.EstimateLineInput(
            line_kind="option",
            product_id="25560063",
            parent_product_id="25454886",
            relation_id="relation-1",
            offer_operation="getMASCntrctPrdctInfoList",
            offer_key="offer-parent",
            item_name_snapshot="저장장치",
            spec_snapshot="8TB",
            company_snapshot="관계 공급사",
            unit_snapshot="개",
            unit_price_won_snapshot=5_431_000,
            quantity=Decimal("2.75"),
        ),
    )


def test_facade_replace_replays_exact_document_and_reuses_comparisons(
    tmp_path: Path,
) -> None:
    """The public facade keeps replay and reseeding order stable."""
    database = tmp_path / "g2b.sqlite3"
    store = services.EstimateStore(database)
    seen_comparison_counts: list[int] = []

    def seed(connection: sqlite3.Connection, lines: tuple[EstimateLine, ...]) -> None:
        count = query(
            connection,
            "SELECT COUNT(*) FROM estimate_comparisons WHERE estimate_line_id = ?",
            (lines[0].id,),
        ).fetchone()
        assert count is not None
        comparison_count = as_int(count[0])
        seen_comparison_counts.append(comparison_count)
        if comparison_count == 0:
            _ = query(
                connection,
                "INSERT INTO estimate_comparisons VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    lines[0].id,
                    "A",
                    lines[0].product_id,
                    None,
                    "공급사",
                    "800만화소",
                    100,
                ),
            )

    first = store.replace_draft(
        "a" * 32,
        "CCTV 구매 설치",
        "a" * 64,
        (("b" * 32, _item()),),
        seed,
    )
    replayed = store.replace_draft(
        first.id,
        first.title,
        first.template_sha256,
        ((first.lines[0].id, _item()),),
        seed,
    )
    quantity_changed = store.replace_draft(
        first.id,
        first.title,
        first.template_sha256,
        ((first.lines[0].id, _item(quantity=Decimal("3.5"))),),
        seed,
    )

    assert replayed == first
    assert quantity_changed.lines[0].quantity == Decimal("3.5")
    assert seen_comparison_counts == [0, 1, 1]


def test_facade_replace_rolls_back_draft_lines_and_seeded_comparisons(
    tmp_path: Path,
) -> None:
    """A failed reseed leaves a whole-document replacement invisible."""
    store = services.EstimateStore(tmp_path / "g2b.sqlite3")

    def interrupted_seed(
        connection: sqlite3.Connection,
        lines: tuple[EstimateLine, ...],
    ) -> None:
        _ = query(
            connection,
            "INSERT INTO estimate_comparisons VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lines[0].id, "A", lines[0].product_id, None, "공급사", "800만화소", 100),
        )
        raise RuntimeError(RESEED_FAILURE)

    with pytest.raises(RuntimeError, match=RESEED_FAILURE):
        _ = store.replace_draft(
            "a" * 32,
            "CCTV 구매 설치",
            "a" * 64,
            (("b" * 32, _item()),),
            interrupted_seed,
        )

    with sqlite3.connect(store.database) as connection:
        assert connection.execute("SELECT * FROM estimate_drafts").fetchall() == []
        assert connection.execute("SELECT * FROM estimate_lines").fetchall() == []
        assert connection.execute("SELECT * FROM estimate_comparisons").fetchall() == []
