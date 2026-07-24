from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI

from g2b_compare.web.estimate_api import build_estimate_api_router

from .test_estimate_routes import _seed_product

# noqa: SIZE_OK - One focused contract file covers the single estimate API surface.

if TYPE_CHECKING:
    from pathlib import Path

ESTIMATE_ID = "a" * 32
LINE_ID = "b" * 32


def _api_app(database: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(build_estimate_api_router(database))
    return app


def test_estimate_api_exposes_server_sent_event_stream(tmp_path: Path) -> None:
    # Given: the estimate API router.
    router = build_estimate_api_router(tmp_path / "g2b.sqlite3")

    # When: its registered HTTP paths are inspected.
    paths = {route.path for route in router.routes}

    # Then: clients can keep one SSE connection for estimate changes.
    assert "/api/estimates/events" in paths


def _line(
    *,
    line_id: str = LINE_ID,
    product_id: str = "25454886",
    quantity: str = "2",
) -> dict[str, str | int | None]:
    return {
        "id": line_id,
        "line_kind": "main",
        "product_id": product_id,
        "parent_product_id": None,
        "relation_id": None,
        "offer_operation": "getMASCntrctPrdctInfoList",
        "offer_key": f"offer-{product_id}",
        "item_name_snapshot": "Camera",
        "spec_snapshot": "8 MP",
        "company_snapshot": "주식회사 코리아넷",
        "unit_snapshot": "each",
        "unit_price_won_snapshot": 1_000,
        "quantity": quantity,
    }


def _document(
    lines: list[dict[str, str | int | None]] | None = None,
) -> dict[str, str | list[dict[str, str | int | None]]]:
    return {"title": "Cached estimate", "lines": lines or [_line()]}


def _seed_three_products(database: Path) -> None:
    _seed_product(
        database,
        "25454886",
        price_won=1_000,
        company_name="주식회사 코리아넷",
        spec="8 MP",
    )
    _seed_product(
        database,
        "25454887",
        price_won=1_050,
        company_name="B Corp",
        spec="8 MP",
    )
    _seed_product(
        database,
        "25454888",
        price_won=1_100,
        company_name="C Corp",
        spec="8 MP",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET raw_json = ? WHERE product_id = ?",
            (
                '{"pdctAtrbNm":"01$x$x$x$Resolution$ATTR1","pdctAtrbCdDtlNm":"8 MP"}',
                "25454886",
            ),
        )


@pytest.mark.asyncio
async def test_put_replay_is_exact_and_quantity_only_reuses_comparisons(
    tmp_path: Path,
) -> None:
    # Given: one catalog selection with enough distinct-company comparisons.
    database = tmp_path / "g2b.sqlite3"
    _seed_three_products(database)
    app = _api_app(database)
    payload = _document()

    # When: the same full document is replayed twice, then only quantity changes.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=payload)
        second = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=payload)
        with sqlite3.connect(database) as connection:
            comparisons_before = connection.execute(
                "SELECT * FROM estimate_comparisons ORDER BY slot"
            ).fetchall()
            connection.execute(
                "UPDATE priority_products SET company_name = ? WHERE product_id = ?",
                ("Changed B Corp", "25454887"),
            )
        quantity_payload = deepcopy(payload)
        quantity_payload["lines"][0]["quantity"] = "3.5"
        changed = await client.put(
            f"/api/estimates/{ESTIMATE_ID}", json=quantity_payload
        )
        detail = await client.get(f"/api/estimates/{ESTIMATE_ID}")
        saved = await client.get("/api/estimates")

    # Then: IDs/state are exact, quantities do not accumulate, and A/B/C stay pinned.
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert changed.status_code == 200
    assert detail.status_code == 200
    assert saved.status_code == 200
    body = detail.json()
    assert body["id"] == ESTIMATE_ID
    assert body["lines"][0]["id"] == LINE_ID
    assert body["lines"][0]["quantity"] == "3.5"
    assert body["lines"][0]["attributes"] == [
        {"name": "Resolution", "value": "8 MP", "unit": ""}
    ]
    assert [item["slot"] for item in body["lines"][0]["comparisons"]] == [
        "A",
        "B",
        "C",
    ]
    assert [item["g2b_url"] for item in body["lines"][0]["comparisons"]] == [
        "https://shop.g2b.go.kr/detail",
        "https://shop.g2b.go.kr/detail",
        "https://shop.g2b.go.kr/detail",
    ]
    assert body["export_ready"] is True
    assert saved.json()[0]["id"] == ESTIMATE_ID
    with sqlite3.connect(database) as connection:
        lines = connection.execute("SELECT id, quantity FROM estimate_lines").fetchall()
        comparisons_after = connection.execute(
            "SELECT * FROM estimate_comparisons ORDER BY slot"
        ).fetchall()
    assert lines == [(LINE_ID, 3.5)]
    assert comparisons_after == comparisons_before


@pytest.mark.asyncio
async def test_product_identity_change_keeps_koreanet_as_comparison_a(
    tmp_path: Path,
) -> None:
    # Given: a persisted line anchored to Koreanet.
    database = tmp_path / "g2b.sqlite3"
    _seed_three_products(database)
    app = _api_app(database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        _ = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=_document())
        changed_line = _line(product_id="25454887")
        changed_line["company_snapshot"] = "B Corp"
        changed_line["unit_price_won_snapshot"] = 1_050

        # When: the same client line ID points at a different product identity.
        response = await client.put(
            f"/api/estimates/{ESTIMATE_ID}", json=_document([changed_line])
        )

    # Then: comparison A remains the Koreanet baseline.
    assert response.status_code == 200
    comparisons = response.json()["lines"][0]["comparisons"]
    assert comparisons[0]["slot"] == "A"
    assert comparisons[0]["product_id"] == "25454886"


@pytest.mark.asyncio
async def test_stale_option_snapshot_is_preserved_and_not_export_ready(
    tmp_path: Path,
) -> None:
    # Given: a cached option whose source relation disappeared before first replay.
    database = tmp_path / "g2b.sqlite3"
    _seed_product(
        database,
        "25454886",
        price_won=1_000,
        company_name="Parent Corp",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO verified_product_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cached-relation",
                "getMASCntrctPrdctInfoList",
                "offer-parent",
                "25454886",
                "25560063",
                "additional",
                1,
                "Cached Corp",
                "Cached option",
                500,
                "https://example.test/option",
                "2026-07-21T00:00:00+00:00",
                1,
            ),
        )
        connection.execute(
            "DELETE FROM verified_product_options WHERE relation_id = ?",
            ("cached-relation",),
        )
    option = _line(product_id="25560063")
    option.update(
        {
            "line_kind": "option",
            "parent_product_id": "25454886",
            "relation_id": "cached-relation",
            "item_name_snapshot": "Cached option",
            "spec_snapshot": "Cached 8 TB",
            "company_snapshot": "Cached Corp",
            "unit_price_won_snapshot": 500,
        }
    )
    app = _api_app(database)

    # When: the offline cached document is replayed.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            f"/api/estimates/{ESTIMATE_ID}", json=_document([option])
        )

    # Then: cached selected fields survive while missing candidates block export.
    assert response.status_code == 200
    body = response.json()
    assert body["lines"][0]["relation_id"] == "cached-relation"
    assert body["lines"][0]["item_name_snapshot"] == "Cached option"
    comparison_slots = [item["slot"] for item in body["lines"][0]["comparisons"]]
    assert comparison_slots == []
    assert body["export_ready"] is False


@pytest.mark.asyncio
async def test_invalid_documents_do_not_partially_replace_existing_state(
    tmp_path: Path,
) -> None:
    # Given: one valid persisted document.
    database = tmp_path / "g2b.sqlite3"
    _seed_three_products(database)
    app = _api_app(database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        original = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=_document())

        # When: empty, malformed, duplicate, and over-capacity documents arrive.
        empty = await client.put(
            f"/api/estimates/{ESTIMATE_ID}",
            json={"title": "Empty", "lines": []},
        )
        malformed = await client.put("/api/estimates/not-hex", json=_document())
        duplicate = await client.put(
            f"/api/estimates/{ESTIMATE_ID}",
            json=_document([_line(), _line()]),
        )
        too_many = await client.put(
            f"/api/estimates/{ESTIMATE_ID}",
            json=_document(
                [
                    _line(line_id=f"{index:032x}", product_id=f"25{index:06d}")
                    for index in range(10)
                ]
            ),
        )
        persisted = await client.get(f"/api/estimates/{ESTIMATE_ID}")

    # Then: stable client errors leave the original transaction untouched.
    assert original.status_code == 200
    assert empty.status_code == 422
    assert malformed.status_code == 422
    assert duplicate.status_code == 422
    assert too_many.status_code == 409
    assert persisted.json() == original.json()


@pytest.mark.asyncio
async def test_interrupted_replace_rolls_back_and_retry_applies_once(
    tmp_path: Path,
) -> None:
    # Given: a saved document and a trigger that interrupts the final draft touch.
    database = tmp_path / "g2b.sqlite3"
    _seed_three_products(database)
    app = _api_app(database)
    retry_payload = _document([_line(quantity="7")])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        original = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=_document())
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TRIGGER fail_document_touch "
                "BEFORE UPDATE OF updated_at ON estimate_drafts "
                "BEGIN SELECT RAISE(ABORT, 'forced interruption'); END"
            )

        # When: replacement is interrupted and the identical latest state is retried.
        interrupted = await client.put(
            f"/api/estimates/{ESTIMATE_ID}", json=retry_payload
        )
        after_failure = await client.get(f"/api/estimates/{ESTIMATE_ID}")
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER fail_document_touch")
        retried = await client.put(f"/api/estimates/{ESTIMATE_ID}", json=retry_payload)

    # Then: the failed attempt is atomic and retry sets, rather than adds, quantity.
    assert interrupted.status_code == 500
    assert after_failure.json() == original.json()
    assert retried.status_code == 200
    assert retried.json()["lines"][0]["quantity"] == "7"
    with sqlite3.connect(database) as connection:
        count_and_quantity = connection.execute(
            "SELECT COUNT(*), quantity FROM estimate_lines"
        ).fetchone()
    assert count_and_quantity == (1, 7)


@pytest.mark.asyncio
async def test_missing_detail_and_repeated_delete_have_locked_statuses(
    tmp_path: Path,
) -> None:
    # Given: an empty API database.
    database = tmp_path / "g2b.sqlite3"
    app = _api_app(database)

    # When: detail is read and delete is replayed for the same absent ID.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get(f"/api/estimates/{ESTIMATE_ID}")
        first = await client.delete(f"/api/estimates/{ESTIMATE_ID}")
        second = await client.delete(f"/api/estimates/{ESTIMATE_ID}")

    # Then: missing reads are 404 and deletes are idempotent 204.
    assert missing.status_code == 404
    assert first.status_code == 204
    assert second.status_code == 204
