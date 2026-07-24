from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from g2b_compare.web import app as app_module


FRONTEND_DIST = Path("src/g2b_compare/web/frontend_dist")


@pytest.mark.asyncio
async def test_spa_deep_links_preserve_non_spa_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (FRONTEND_DIST / "index.html").is_file(), "fresh production SPA bundle is required"
    monkeypatch.setattr(app_module, "FRONTEND_DIST", FRONTEND_DIST)
    monkeypatch.setenv("G2B_SERVE_SPA", "1")
    index = (FRONTEND_DIST / "index.html").read_text(encoding="utf-8")
    css_match = re.search(r'href="(/assets/[^"]+\.css)"', index)
    assert css_match is not None
    css_path = css_match.group(1)
    app = app_module.create_app(database=tmp_path / "g2b.sqlite3", home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        core = await client.get("/"), await client.get("/estimates"), await client.get(
            f"/estimates/{'a' * 32}"
        ), await client.get("/data")
        legacy = await client.get("/live"), await client.get("/priority"), await client.get(
            "/sync"
        )
        unknown_api = await client.get("/api/not-a-route")
        missing_export = await client.get(f"/estimates/{'a' * 32}/export.xlsx")
        health = await client.get("/healthz")
        asset = await client.get(css_path)
        worker = await client.get("/sw.js")

    assert all(response.status_code == 200 for response in core)
    assert all(response.text == index for response in core)
    assert all(response.status_code == 200 for response in legacy)
    assert all(response.text != index for response in legacy)
    assert unknown_api.status_code == 404
    assert unknown_api.headers["content-type"].startswith("application/json")
    assert missing_export.status_code == 404
    assert missing_export.text != index
    assert health.headers["content-type"].startswith("application/json")
    assert asset.headers["content-type"].startswith("text/css")
    assert asset.content == (FRONTEND_DIST / css_path.lstrip("/")).read_bytes()
    assert worker.headers["content-type"].startswith("application/javascript")
    assert worker.content == (FRONTEND_DIST / "sw.js").read_bytes()


def test_required_production_build_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "FRONTEND_DIST", tmp_path / "missing")
    monkeypatch.setenv("G2B_REQUIRE_FRONTEND_DIST", "1")
    monkeypatch.setenv("G2B_SERVE_SPA", "1")

    with pytest.raises(RuntimeError, match="Production SPA build is missing"):
        app_module.create_app(database=tmp_path / "g2b.sqlite3", home=tmp_path)
