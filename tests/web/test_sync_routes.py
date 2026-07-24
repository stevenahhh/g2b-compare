from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

from g2b_compare.db.migrate import migrate
from g2b_compare.web.app import create_app
from g2b_compare.web.sync_routes import STATUS_FILENAME, SyncStatus

POLL_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.05
LINK_MANIFEST = Path("docs/api-contract-observed.json")


def _client(database: Path, home: Path) -> httpx.AsyncClient:
    migrate(database)
    transport = httpx.ASGITransport(
        app=create_app(database=database, link_manifest=LINK_MANIFEST, home=home)
    )
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _fake_cli(
    fake_bin: Path,
    command_log: Path,
    *,
    fail_on_stage: str | None,
) -> None:
    fake_bin.mkdir(parents=True, exist_ok=True)
    failure_check = (
        ""
        if fail_on_stage is None
        else f"""
echo %* | findstr /C:"{fail_on_stage}" >nul
if not errorlevel 1 exit /b 1
"""
    )
    _ = (fake_bin / "g2b-compare.cmd").write_text(
        f"""@echo off
echo %*>>"{command_log}"
{failure_check}
exit /b 0
""",
        encoding="ascii",
    )


def _poll_status(status_path: Path) -> SyncStatus:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if status_path.is_file():
            status = SyncStatus.model_validate_json(status_path.read_bytes())
            if status.state in {"complete", "failed"}:
                return status
        time.sleep(POLL_INTERVAL_SECONDS)
    message = "manual sync did not finish before the test timeout"
    raise AssertionError(message)


@pytest.mark.anyio
async def test_sync_get_reports_idle_status_when_never_run(tmp_path: Path) -> None:
    # Given: a fresh home that has never run a manual sync.
    async with _client(tmp_path / "g2b.sqlite3", tmp_path / "home") as client:
        # When
        response = await client.get("/sync")

    # Then
    assert response.status_code == 200
    assert "아직 동기화한 적이 없습니다" in response.text


@pytest.mark.anyio
async def test_sync_post_runs_every_stage_and_reports_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fake CLI on PATH that succeeds for every stage.
    home = tmp_path / "home"
    fake_bin = tmp_path / "fake-bin"
    command_log = tmp_path / "commands.log"
    _fake_cli(fake_bin, command_log, fail_on_stage=None)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    async with _client(tmp_path / "g2b.sqlite3", home) as client:
        # When
        response = await client.post("/sync", follow_redirects=False)
        status = _poll_status(home / STATUS_FILENAME)

    # Then
    assert response.status_code == 303
    assert status.state == "complete"
    logged = command_log.read_text(encoding="ascii")
    for stage in ("sync full", "import-relations", "materialize"):
        assert stage in logged


@pytest.mark.anyio
async def test_sync_post_reports_the_failing_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fake CLI that fails specifically on materialize.
    home = tmp_path / "home"
    fake_bin = tmp_path / "fake-bin"
    command_log = tmp_path / "commands.log"
    _fake_cli(fake_bin, command_log, fail_on_stage="materialize")
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    async with _client(tmp_path / "g2b.sqlite3", home) as client:
        # When
        _ = await client.post("/sync", follow_redirects=False)
        status = _poll_status(home / STATUS_FILENAME)

    # Then
    assert status.state == "failed"
    assert status.stage == "materialize"
