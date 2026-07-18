from __future__ import annotations

import gzip
import importlib
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

import pytest

from g2b_compare.cli import main
from g2b_compare.db.migrate import migrate
from g2b_compare.observability.health import health, readiness
from g2b_compare.observability.secrets import CANARY
from g2b_compare.sync.catalog import advance_catalog
from tests.acceptance.todo_12_release_support import ready_candidate
from tests.sync.todo8_fixture import (
    NOW,
    complete_products,
    setup_five_sources,
)
from tests.sync.todo8_fixture import (
    database as sync_database,
)

FAILURE_IDS = (
    "missing-key",
    "live-gate",
    "corrupt-db",
    "corrupt-index",
    "port-occupied",
    "stale",
    "ctrl-c-sync",
    "secret-log",
    "secret-db",
    "secret-gzip",
)


def test_happy(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    index = tmp_path / "search-index.bin"
    assert main(("--home", str(tmp_path), "init-db")) == 0
    _ = index.write_bytes(b"index")
    assert health(database, index).ok
    assert main(("--home", str(tmp_path), "verify-secrets")) == 0


def test_fresh_home_rebuild_index_is_typed_and_builds_seeded_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: a freshly initialized HOME has no complete materialization.
    assert main(("--home", str(tmp_path), "init-db")) == 0

    # When: rebuild is requested before and after a complete candidate is persisted.
    assert main(("--home", str(tmp_path), "rebuild-index")) == 1
    blocked = capsys.readouterr()
    _fixture, _result = ready_candidate(tmp_path / "g2b.sqlite3")
    assert main(("--home", str(tmp_path), "rebuild-index")) == 0

    # Then: the missing prerequisite is typed and the index is written.
    assert '"status": "blocked"' in blocked.err
    artifact = tmp_path / "search-index.bin"
    assert artifact.is_file()
    assert artifact.stat().st_size > 0


def test_installed_commands_materialize_sources_before_rebuilding_index(
    tmp_path: Path,
) -> None:
    # Given: the persisted five-source catalog and complete attribute prerequisite.
    database = tmp_path / "g2b.sqlite3"
    fixture = sync_database(database)
    setup_five_sources(fixture)
    advance = advance_catalog(database, NOW)
    _ = complete_products(fixture, advance, ("P-1",))

    # When: the installed production build commands run in dependency order.
    assert main(("--home", str(tmp_path), "materialize")) == 0
    assert main(("--home", str(tmp_path), "rebuild-index")) == 0

    # Then: both the complete candidate and binary index are real persisted artifacts.
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM materialization_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone() == ("complete",)
    assert (tmp_path / "search-index.bin").stat().st_size > 0


def test_start_script_provisions_fresh_home_in_dependency_order(tmp_path: Path) -> None:
    # Given: fixture inputs and a process-level fake for every external uv command.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    home = tmp_path / "home"
    log = tmp_path / "commands.log"
    ready = tmp_path / "ready.marker"
    secret = tmp_path / "secret.txt"
    relations = tmp_path / "relations.xlsx"
    _ = secret.write_text("fixture-key", encoding="utf-8")
    _ = relations.write_bytes(b"fixture")
    fake_uv = fake_bin / "uv.cmd"
    _ = fake_uv.write_text(
        """@echo off
echo %*>>"%G2B_FAKE_LOG%"
echo %*| findstr /C:" capture-contract" >nul && (
  mkdir "%G2B_FAKE_HOME%\\docs" 2>nul
  copy /Y "%G2B_FAKE_CONTRACT%" "%G2B_FAKE_HOME%\\docs\\api-contract-observed.json" >nul
)
echo %*| findstr /C:" precompute" >nul && echo ready>"%G2B_FAKE_READY%"
echo %*| findstr /C:" verify-secrets" >nul && exit /b 0
echo %*| findstr /C:" verify" >nul && if not exist "%G2B_FAKE_READY%" exit /b 1
exit /b 0
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "G2B_SERVICE_KEY": "fixture-runtime-key",
        "G2B_SECRET_SOURCE": str(secret),
        "G2B_RELATIONS_WORKBOOK": str(relations),
        "G2B_FAKE_LOG": str(log),
        "G2B_FAKE_HOME": str(home),
        "G2B_FAKE_READY": str(ready),
        "G2B_FAKE_CONTRACT": str(Path("docs/api-contract-observed.json").resolve()),
    }

    # When: the real PowerShell fresh workflow runs in bounded provisioning mode.
    completed = subprocess.run(  # noqa: S603
        (
            shutil.which("pwsh") or shutil.which("powershell") or "powershell",
            "-NoProfile",
            "-File",
            str(Path("scripts/start.ps1").resolve()),
            "-HomePath",
            str(home),
            "-ProvisionOnly",
        ),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    # Then: every required stage ran in dependency order with all-storage verification.
    assert completed.returncode == 0, completed.stderr
    commands = log.read_text(encoding="utf-8")
    expected = (
        "capture-contract",
        "sync full",
        "sync attributes --max-batches 100",
        "import-relations",
        "materialize",
        "rebuild-index",
        "precompute",
        "verify-secrets --all-storage",
    )
    positions = tuple(commands.index(item) for item in expected)
    assert positions == tuple(sorted(positions))


@pytest.mark.parametrize("scenario", FAILURE_IDS, ids=FAILURE_IDS)
def test_failure_scenario_matches_registry_contract(
    scenario: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    if scenario == "missing-key":
        monkeypatch.delenv("G2B_SERVICE_KEY", raising=False)
        assert main(("--home", str(tmp_path), "sync", "delta")) == 2
    elif scenario == "live-gate":
        _fixture, _result = ready_candidate(database)
        index = tmp_path / "search-index.bin"
        _ = index.write_bytes(b"fixture")
        _patch_readiness(monkeypatch, contract_verified=False)
        assert readiness(database, index_path=index).status == "live-gate"
    elif scenario == "stale":
        _fixture, _result = ready_candidate(database)
        index = tmp_path / "search-index.bin"
        _ = index.write_bytes(b"fixture")
        with sqlite3.connect(database) as connection:
            _ = connection.execute(
                """INSERT INTO relation_snapshots
                   VALUES(999,'new-manifest','new-content','complete',?)""",
                ("2099-01-01T00:00:00+00:00",),
            )
        _patch_readiness(monkeypatch, contract_verified=True)
        probe = readiness(database, index_path=index)
        assert probe.ok
        assert probe.detail["data_statuses"] == ["stale"]
    elif scenario == "corrupt-db":
        _ = database.write_bytes(b"not sqlite")
        assert health(database).status == "corrupt-db"
    elif scenario == "corrupt-index":
        migrate(database)
        assert health(database, tmp_path / "missing.index").status == "corrupt-index"
    elif scenario == "port-occupied":
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            address = cast("tuple[str, int]", occupied.getsockname())
            port = address[1]
            assert main(("serve", "--port", str(port))) == 2
    elif scenario == "ctrl-c-sync":
        _assert_ctrl_c_sync_stops_process(tmp_path)
    else:
        home = tmp_path / "runtime"
        home.mkdir()
        suffix = {"secret-log": ".log", "secret-db": ".sqlite3", "secret-gzip": ".gz"}[
            scenario
        ]
        artifact = home / f"artifact{suffix}"
        if scenario == "secret-gzip":
            with gzip.open(artifact, "wb") as stream:
                _ = stream.write(CANARY)
        elif scenario == "secret-db":
            with sqlite3.connect(artifact) as connection:
                _ = connection.execute("CREATE TABLE evidence(value TEXT)")
                _ = connection.execute(
                    "INSERT INTO evidence VALUES (?)",
                    (CANARY.decode(),),
                )
        else:
            _ = artifact.write_bytes(CANARY)
        assert main(("--home", str(home), "verify-secrets", "--all-storage")) == 1


def _patch_readiness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    contract_verified: bool,
) -> None:
    health_module = importlib.import_module("g2b_compare.observability.health")

    def fixture_digest(_path: Path) -> str:
        return "b" * 64

    def fixture_contract(_path: Path) -> bool:
        return contract_verified

    monkeypatch.setattr(health_module, "_sha256", fixture_digest)
    monkeypatch.setattr(health_module, "_verified_contract", fixture_contract)


def _assert_ctrl_c_sync_stops_process(tmp_path: Path) -> None:
    fake_bin = tmp_path / "ctrl-bin"
    fake_bin.mkdir()
    marker = tmp_path / "sync-started"
    helper = tmp_path / "signal_helper.py"
    _ = helper.write_text(
        """import os
import signal
import sys
import time

with open(os.environ["G2B_CTRL_MARKER"], "w", encoding="utf-8") as stream:
    stream.write("started")

def stop(_signal, _frame):
    raise SystemExit(130)

signal.signal(signal.SIGBREAK, stop)
while True:
    time.sleep(1)
""",
        encoding="utf-8",
    )
    fake_uv = fake_bin / "uv.cmd"
    _ = fake_uv.write_text(
        """@echo off
if "%1"=="sync" exit /b 0
"%G2B_PYTHON%" "%G2B_CTRL_HELPER%"
exit /b %ERRORLEVEL%
""",
        encoding="utf-8",
    )
    executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "G2B_CTRL_MARKER": str(marker),
        "G2B_CTRL_HELPER": str(helper),
        "G2B_PYTHON": sys.executable,
    }
    process = subprocess.Popen(  # noqa: S603
        (
            executable,
            "-NoProfile",
            "-File",
            str(Path("scripts/sync.ps1").resolve()),
            "-HomePath",
            str(tmp_path / "home"),
        ),
        env=environment,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            pass
        assert marker.exists()
        process.send_signal(signal.CTRL_BREAK_EVENT)
        assert process.wait(timeout=10) == 130
    finally:
        if process.poll() is None:
            process.kill()
            _ = process.wait(timeout=10)
