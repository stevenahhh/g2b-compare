from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from g2b_compare.db.sql import as_text, query
from g2b_compare.priority_store import PriorityStore
from g2b_compare.runtime_database import build_runtime_database

if TYPE_CHECKING:
    from pathlib import Path


def test_build_runtime_database_keeps_only_runtime_product_payload(
    tmp_path: Path,
) -> None:
    # Given: one collected product and offer with the complete provider payload.
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "runtime.sqlite3"
    _ = PriorityStore(source)
    raw = json.dumps(
        {
            "pdctAtrbNm": "용도|구성",
            "pdctAtrbCdDtlNm": "옥내감시$카메라",
            "snymNm": "2MP/4배줌",
            "ctrtItemMngNo": "0023H0324_1040000122",
            "ctrtNo": "0023H0324_1",
            "ctrtChgOrd": "04",
            "unusedProviderField": "remove-me",
        },
        ensure_ascii=False,
    )
    with sqlite3.connect(source) as connection:
        _ = connection.execute(
            """
            INSERT INTO priority_products (
                product_id, operation, contract_number, contract_sequence,
                category_number, category_name, detail_category_number, spec,
                company_name, unit, price_won, contract_method,
                delivery_condition, delivery_days, contract_end_date, image_url,
                detail_url, raw_json, observed_at
            ) VALUES (
                '25000001', 'catalog', 'contract', '1', 'category',
                '영상감시장치', '', '영상감시장치, 시험', '코리아넷', '조',
                1000, '다수공급자계약', '현장설치도', '60일', '20261231',
                'https://example.test/image.jpg',
                'https://example.test/product', ?, '2026-07-28'
            )
            """,
            (raw,),
        )
        _ = connection.execute(
            """
            INSERT INTO priority_product_offers (
                operation, offer_key, product_id, company_name, price_won, unit,
                contract_method, delivery_condition, delivery_days,
                contract_end_date, image_url, detail_url, raw_json, observed_at,
                active
            ) VALUES (
                'catalog', 'offer-1', '25000001', '코리아넷', 1000, '조',
                '다수공급자계약', '현장설치도', '60일', '20261231',
                'https://example.test/image.jpg',
                'https://example.test/product', ?, '2026-07-28', 1
            )
            """,
            (raw,),
        )

    # When: a separate runtime database is built.
    result = build_runtime_database(source, destination)

    # Then: runtime fields remain, duplicate payload is removed, and source is intact.
    with sqlite3.connect(destination) as connection:
        product_raw = query(
            connection,
            "SELECT raw_json FROM priority_products WHERE product_id = '25000001'"
        ).fetchone()
        offer_raw = query(
            connection,
            "SELECT raw_json FROM priority_product_offers"
        ).fetchone()
    with sqlite3.connect(source) as connection:
        source_raw = query(
            connection,
            "SELECT raw_json FROM priority_products WHERE product_id = '25000001'"
        ).fetchone()
    assert product_raw is not None
    assert TypeAdapter(dict[str, str]).validate_json(as_text(product_raw[0])) == {
        "pdctAtrbNm": "용도|구성",
        "pdctAtrbCdDtlNm": "옥내감시$카메라",
        "snymNm": "2MP/4배줌",
        "ctrtItemMngNo": "0023H0324_1040000122",
        "ctrtNo": "0023H0324_1",
        "ctrtChgOrd": "04",
    }
    assert offer_raw is not None
    assert as_text(offer_raw[0]) == "{}"
    assert source_raw is not None
    assert as_text(source_raw[0]) == raw
    assert result.destination == destination.resolve()
