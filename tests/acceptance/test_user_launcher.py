from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_root_batch_launcher_delegates_to_user_start_script() -> None:
    launcher = (PROJECT_ROOT / "START_APP.bat").read_text(encoding="utf-8")

    assert "scripts\\start-user.ps1" in launcher
    assert "update-from-github.ps1" not in launcher
    assert "-ExecutionPolicy Bypass" in launcher
    assert "pause" in launcher.lower()


def test_user_start_script_help_needs_no_runtime_dependencies() -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    result = subprocess.run(  # noqa: S603
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "start-user.ps1"),
            "-Help",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )

    output = _decode_powershell(result.stdout)
    assert result.returncode == 0, _decode_powershell(result.stderr)
    assert "START_APP.bat" in output
    assert "http://127.0.0.1:8765/" in output
    assert "Ctrl+C" in output


def test_quick_start_uses_single_double_click_entrypoint() -> None:
    guide = (PROJECT_ROOT / "QUICK_START.txt").read_text(encoding="utf-8")

    assert "START_APP.bat" in guide
    assert "더블클릭" in guide
    assert ".env" in guide
    assert "Ctrl+C" in guide
    assert "자동으로 설치" in guide


def test_user_launcher_can_install_python_without_manual_setup() -> None:
    launcher = (PROJECT_ROOT / "scripts" / "start-user.ps1").read_text(
        encoding="utf-8"
    )

    assert "winget" in launcher
    assert "Python.Python.3.12" in launcher
    assert "python-3.12.10-amd64.exe" in launcher
    assert "InstallAllUsers=0" in launcher


def _decode_powershell(value: bytes) -> str:
    if value.startswith((b"\xff\xfe", b"\xfe\xff")):
        return value.decode("utf-16")
    try:
        return value.decode("utf-8-sig")
    except UnicodeDecodeError:
        return value.decode("utf-16-le")
