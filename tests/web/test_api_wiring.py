from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from g2b_compare.web.app import create_app


@pytest.mark.asyncio
async def test_create_app_exposes_spa_json_routers(tmp_path: Path) -> None:
    # Given: a fresh application database.
    database = tmp_path / "g2b.sqlite3"
    app = create_app(database=database, home=tmp_path)

    # When: the SPA requests each JSON collection endpoint.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await client.get("/api/catalog/products"), await client.get(
            "/api/estimates"
        ), await client.get("/api/data/status")

    # Then: all three routers are reachable through the integrated app.
    assert [response.status_code for response in responses] == [200, 200, 200]
