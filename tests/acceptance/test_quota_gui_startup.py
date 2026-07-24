from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from pydantic import TypeAdapter

JSON_DOCUMENT = TypeAdapter(dict[str, str])
QUOTA_RECEIPT = (
    '{"error":"quota-ceiling-exhausted",'
    '"operation":"getMASCntrctPrdctInfoList",'
    '"resume_not_before":"2026-07-19T15:01:28.112741+00:00",'
    '"status":"blocked"}'
)


def test_launcher_defers_quota_block_to_runtime_status(tmp_path: Path) -> None:
    # Given: a fresh launcher whose catalog sync reaches the rolling quota ceiling.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    home = tmp_path / "home"
    log = tmp_path / "commands.log"
    fake_uv = fake_bin / "uv.cmd"
    _ = fake_uv.write_text(
        f"""@echo off
echo %*>>"%G2B_FAKE_LOG%"
echo %*| findstr /C:" sync full" >nul && (
  echo {QUOTA_RECEIPT} 1>&2
  exit /b 2
)
echo %*| findstr /C:" verify-secrets" >nul && exit /b 0
echo %*| findstr /C:" verify" >nul && exit /b 1
exit /b 0
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "G2B_SERVICE_KEY": "fixture-runtime-key",
        "G2B_FAKE_LOG": str(log),
    }

    # When: the real PowerShell launcher provisions without opening the server.
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
        env=environment,
    )

    # Then: quota state is persisted for the GUI and later build stages are deferred.
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    status = JSON_DOCUMENT.validate_json((home / "quota-status.json").read_bytes())
    assert status["error"] == "quota-ceiling-exhausted"
    assert status["operation"] == "getMASCntrctPrdctInfoList"
    commands = log.read_text(encoding="utf-8")
    assert "sync attributes" not in commands
    assert " materialize" not in commands
    assert " rebuild-index" not in commands
    assert " precompute" not in commands
