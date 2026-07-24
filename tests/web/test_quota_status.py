from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from g2b_compare.db.migrate import migrate
from g2b_compare.web.app import create_app


@pytest.mark.anyio
async def test_no_active_release_displays_persisted_quota_status(
    tmp_path: Path,
) -> None:
    # Given: no active release and a quota receipt persisted by the launcher.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    _ = (tmp_path / "quota-status.json").write_text(
        json.dumps(
            {
                "error": "quota-ceiling-exhausted",
                "operation": "getMASCntrctPrdctInfoList",
                "resume_not_before": "2026-07-19T15:01:28.112741+00:00",
                "status": "blocked",
            }
        ),
        encoding="utf-8",
    )
    transport = httpx.ASGITransport(
        app=create_app(
            database=database,
            link_manifest=Path("docs/api-contract-observed.json"),
        )
    )

    # When: the user opens the GUI while synchronization is deferred.
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    # Then: the page exposes the machine-readable quota operation and resume time.
    assert response.status_code == 503
    assert 'data-quota-operation="getMASCntrctPrdctInfoList"' in response.text
    assert 'datetime="2026-07-19T15:01:28.112741+00:00"' in response.text
    assert "공공데이터포털 실시간 잔여량이 아닌 로컬 기록 기준입니다." in response.text
