from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from g2b_compare import services
from g2b_compare.db.migrate import migrate

if TYPE_CHECKING:
    from pathlib import Path


def _relation(
    relation_id: str,
    parent_product_id: str,
    *,
    parent_offer_key: str,
    price_won: int,
) -> tuple[str, str, str, str, str, str, int, str, str, int, str, str, int]:
    return (
        relation_id,
        "getMASCntrctPrdctInfoList",
        parent_offer_key,
        parent_product_id,
        "25560063",
        "additional",
        1,
        "관계 공급사",
        "[25560063] 저장장치 옵션",
        price_won,
        "https://shop.g2b.go.kr/detail",
        "2026-07-21T00:00:00+00:00",
        1,
    )


def test_contextual_relations_keep_same_option_for_two_parents_and_prices(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    migrate(database)

    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO verified_product_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _relation(
                    "relation-a",
                    "25454886",
                    parent_offer_key="offer-a",
                    price_won=5_431_000,
                ),
                _relation(
                    "relation-b",
                    "25454887",
                    parent_offer_key="offer-b",
                    price_won=6_036_000,
                ),
            ),
        )
        rows = connection.execute(
            "SELECT parent_product_id, relation_price_won "
            "FROM verified_product_options ORDER BY parent_product_id"
        ).fetchall()

    assert rows == [("25454886", 5_431_000), ("25454887", 6_036_000)]


def test_contextual_relation_rejects_parent_self_link(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    invalid = list(
        _relation(
            "relation-self",
            "25560063",
            parent_offer_key="offer-self",
            price_won=1,
        )
    )

    with (
        sqlite3.connect(database) as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            "INSERT INTO verified_product_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            invalid,
        )


def test_estimate_schema_rejects_tenth_line(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    migrate(database)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
            (
                "estimate-1",
                "CCTV 구매 설치",
                "a" * 64,
                "2026-07-21T00:00:00+00:00",
                "2026-07-21T00:00:00+00:00",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO estimate_lines "
                "(id, estimate_id, line_no, line_kind, product_id, "
                "item_name_snapshot, spec_snapshot, company_snapshot, "
                "unit_snapshot, unit_price_won_snapshot, quantity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "line-10",
                    "estimate-1",
                    10,
                    "main",
                    "25454886",
                    "영상감시장치",
                    "800만화소",
                    "공급사",
                    "조",
                    3_281_000,
                    "1",
                ),
            )


def test_estimate_line_keeps_price_snapshot_when_offer_changes(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    migrate(database)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_product_offers "
            "(operation, offer_key, product_id, company_name, price_won, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("getMASCntrctPrdctInfoList", "offer-a", "25454886", "공급사", 100, 1),
        )
        connection.execute(
            "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
            (
                "estimate-1",
                "CCTV 구매 설치",
                "a" * 64,
                "2026-07-21T00:00:00+00:00",
                "2026-07-21T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO estimate_lines "
            "(id, estimate_id, line_no, line_kind, product_id, "
            "offer_operation, offer_key, item_name_snapshot, spec_snapshot, "
            "company_snapshot, unit_snapshot, unit_price_won_snapshot, quantity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "line-1",
                "estimate-1",
                1,
                "main",
                "25454886",
                "getMASCntrctPrdctInfoList",
                "offer-a",
                "영상감시장치",
                "800만화소",
                "공급사",
                "조",
                100,
                "1",
            ),
        )
        connection.execute(
            "UPDATE priority_product_offers SET price_won = 200 "
            "WHERE operation = ? AND offer_key = ?",
            ("getMASCntrctPrdctInfoList", "offer-a"),
        )
        snapshot = connection.execute(
            "SELECT unit_price_won_snapshot FROM estimate_lines WHERE id = 'line-1'"
        ).fetchone()

    assert snapshot == (100,)


def _line(
    product_id: str,
    *,
    relation_id: str | None = None,
    quantity: Decimal = Decimal(1),
) -> services.EstimateLineInput:
    is_option = relation_id is not None
    return services.EstimateLineInput(
        line_kind="option" if is_option else "main",
        product_id=product_id,
        parent_product_id="25454886" if is_option else None,
        relation_id=relation_id,
        offer_operation="getMASCntrctPrdctInfoList",
        offer_key=f"offer-{product_id}",
        item_name_snapshot="저장장치" if is_option else "영상감시장치",
        spec_snapshot="8TB" if is_option else "800만화소",
        company_snapshot="공급사",
        unit_snapshot="개" if is_option else "조",
        unit_price_won_snapshot=100,
        quantity=quantity,
    )


def test_estimate_store_persists_nine_lines_and_rejects_tenth(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = services.EstimateStore(database)
    draft = store.create_draft("CCTV 구매 설치", "a" * 64)

    for index in range(1, 10):
        store.add_line(draft.id, _line(f"25{index:06d}"))

    with pytest.raises(services.EstimateFullError):
        store.add_line(draft.id, _line("25999999"))

    persisted = services.EstimateStore(database).get_draft(draft.id)

    assert persisted.title == "CCTV 구매 설치"
    assert tuple(line.line_no for line in persisted.lines) == tuple(range(1, 10))


def test_estimate_store_merges_duplicate_verified_relation_quantity(
    tmp_path: Path,
) -> None:
    store = services.EstimateStore(tmp_path / "g2b.sqlite3")
    draft = store.create_draft("CCTV 구매 설치", "a" * 64)

    first = store.add_line(
        draft.id,
        _line("25560063", relation_id="relation-a", quantity=Decimal("1.5")),
    )
    second = store.add_line(
        draft.id,
        _line("25560063", relation_id="relation-a", quantity=Decimal("2.25")),
    )

    assert second.id == first.id
    assert second.quantity == Decimal("3.75")
    assert len(store.get_draft(draft.id).lines) == 1


def test_estimate_store_keeps_snapshot_after_source_offer_update(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = services.EstimateStore(database)
    draft = store.create_draft("CCTV 구매 설치", "a" * 64)
    line = store.add_line(draft.id, _line("25454886"))

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_product_offers "
            "(operation, offer_key, product_id, company_name, price_won, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "getMASCntrctPrdctInfoList",
                "offer-25454886",
                "25454886",
                "공급사",
                999,
                1,
            ),
        )

    persisted = store.get_draft(draft.id)

    assert line.unit_price_won_snapshot == 100
    assert persisted.lines[0].unit_price_won_snapshot == 100


def test_estimate_store_rolls_back_line_when_touch_fails(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = services.EstimateStore(database)
    draft = store.create_draft("CCTV 구매 설치", "a" * 64)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_estimate_touch
            BEFORE UPDATE OF updated_at ON estimate_drafts
            BEGIN SELECT RAISE(ABORT, 'forced touch failure'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced touch failure"):
        store.add_line(draft.id, _line("25454886"))

    assert store.get_draft(draft.id).lines == ()


def test_estimate_store_serializes_duplicate_relation_adds(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    store = services.EstimateStore(database)
    draft = store.create_draft("CCTV 구매 설치", "a" * 64)

    def add_relation(_: int) -> services.EstimateLine:
        return store.add_line(
            draft.id,
            _line("25560063", relation_id="relation-a"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        lines = tuple(executor.map(add_relation, range(2)))

    persisted = store.get_draft(draft.id)
    assert lines[0].id == lines[1].id
    assert len(persisted.lines) == 1
    assert persisted.lines[0].quantity == Decimal(2)
