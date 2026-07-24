from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI

from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import (
    CatalogRecord,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)
from g2b_compare.web.api_models import DataStatusResponse
from g2b_compare.web.data_api import build_data_api_router

if TYPE_CHECKING:
    from pathlib import Path


def _seed_status_database(database: Path) -> None:
    store = PriorityStore(database)
    record = CatalogRecord(
        identity=SourceIdentity(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            ("CONTRACT-25000001", "1"),
        ),
        product_id="25000001",
        classification_number="46171622",
        category_name="camera",
        detail_category_number="4617162201",
        spec_name="camera spec",
        contract_price="1000000",
        image_url="",
        timestamp=TimestampEvidence(
            "2026-07-21T00:00:00+00:00",
            TimestampOrigin.OBSERVED_AT_FALLBACK,
            0,
        ),
        raw_fields={
            "cntrctCorpNm": "company",
            "prdctUnit": "each",
            "cntrctMthdNm": "contract",
        },
    )
    store.save_catalog_page(
        company_name="company",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=1,
        total_count=1,
        records=(record,),
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    )


def test_baseline_priority_status_values_remain_unchanged(tmp_path: Path) -> None:
    # Given: the existing shared priority database status source.
    database = tmp_path / "g2b.sqlite3"
    _seed_status_database(database)

    # When: the status is read through the existing service.
    status = PriorityStore(database).status()

    # Then: the persisted counts remain the current /data source values.
    assert status.model_dump() == {
        "company_count": 0,
        "option_row_count": 0,
        "unique_option_count": 0,
        "product_count": 1,
        "relation_count": 0,
        "pending_api_target_count": 0,
        "pending_site_product_count": 1,
    }


@pytest.mark.asyncio
async def test_data_status_endpoint_returns_counts_and_readiness_json(
    tmp_path: Path,
) -> None:
    # Given: a populated shared priority database.
    database = tmp_path / "g2b.sqlite3"
    _seed_status_database(database)
    app = FastAPI()
    app.include_router(build_data_api_router(database))

    # When: the SPA requests the core data status endpoint.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/data/status")

    # Then: counts and readiness are returned as machine-readable JSON.
    assert response.status_code == 200
    assert response.json() == {
        "company_count": 0,
        "option_row_count": 0,
        "unique_option_count": 0,
        "product_count": 1,
        "relation_count": 0,
        "pending_api_target_count": 0,
        "pending_site_product_count": 1,
        "ready": True,
        "readiness": "ready",
    }


@pytest.mark.asyncio
async def test_data_status_endpoint_reports_empty_database_as_not_ready(
    tmp_path: Path,
) -> None:
    # Given: a valid database with no collected products.
    database = tmp_path / "g2b.sqlite3"
    _ = PriorityStore(database)
    app = FastAPI()
    app.include_router(build_data_api_router(database))

    # When: the SPA requests the status.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/data/status")

    # Then: the empty state is a successful, machine-readable response.
    assert response.status_code == 200
    body = DataStatusResponse.model_validate_json(response.content)
    assert body.ready is False
    assert body.readiness == "empty"
    assert body.product_count == 0


@pytest.mark.asyncio
async def test_data_status_endpoint_returns_stable_error_for_unavailable_database(
    tmp_path: Path,
) -> None:
    # Given: a path containing malformed SQLite bytes.
    database = tmp_path / "broken.sqlite3"
    _ = database.write_bytes(b"not a sqlite database")
    app = FastAPI()
    app.include_router(build_data_api_router(database))

    # When: the SPA requests the status.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/data/status")

    # Then: the API exposes a stable unavailable-data error.
    assert response.status_code == 503
    assert response.content == b'{"error":"data-unavailable"}'
