from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StartPyFixture:
    project_root: Path
    fake_bin: Path
    home: Path
    selection_marker: Path
    command_log: Path


def test_start_py_loads_service_key_from_project_dotenv_when_process_key_missing(
    tmp_path: Path,
) -> None:
    # Given: an isolated project has only a dotenv service-key fixture.
    dotenv_value = "dotenv-fixture-value"
    fixture = _prepare_start_py_fixture(tmp_path, dotenv_value)
    environment = _launcher_environment(fixture, dotenv_value)

    # When: provisioning runs through the copied Python launcher.
    completed = _run_start_py(fixture, environment)

    # Then: the fake child receives the dotenv-selected value.
    assert completed.returncode == 0
    assert fixture.selection_marker.read_text(encoding="ascii").strip() == "selected"


def test_start_py_keeps_nonblank_process_service_key_over_project_dotenv(
    tmp_path: Path,
) -> None:
    # Given: the process and dotenv values are distinct.
    dotenv_value = "dotenv-fixture-value"
    process_value = "process-fixture-value"
    fixture = _prepare_start_py_fixture(tmp_path, dotenv_value)
    environment = _launcher_environment(fixture, process_value)
    environment["G2B_SERVICE_KEY"] = process_value

    # When: provisioning runs through the copied Python launcher.
    completed = _run_start_py(fixture, environment)

    # Then: the fake child receives only the process-selected value.
    assert completed.returncode == 0
    assert fixture.selection_marker.read_text(encoding="ascii").strip() == "selected"


def test_start_py_stops_when_secret_verification_fails(tmp_path: Path) -> None:
    # Given: the fake CLI reports a secret-verification failure.
    dotenv_value = "dotenv-fixture-value"
    fixture = _prepare_start_py_fixture(tmp_path, dotenv_value)
    environment = _launcher_environment(fixture, dotenv_value)
    environment["G2B_SIMULATE_VERIFY_FAILURE"] = "true"

    # When: provisioning reaches the secret-verification stage.
    completed = _run_start_py(fixture, environment)

    # Then: the launcher stops and reports the exact failure code.
    launcher_output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "secret-verification-failed" in launcher_output


def test_start_py_does_not_require_prior_data_sync(tmp_path: Path) -> None:
    # Given: a completely fresh home with no local snapshot ever synced.
    dotenv_value = "dotenv-fixture-value"
    fixture = _prepare_start_py_fixture(tmp_path, dotenv_value)
    environment = _launcher_environment(fixture, dotenv_value)

    # When: provisioning runs without any sync-related fixture toggles.
    completed = _run_start_py(fixture, environment)

    # Then: provisioning succeeds and never invokes a sync command.
    command_log = fixture.command_log.read_text(encoding="ascii")
    assert completed.returncode == 0
    assert "sync" not in command_log
    assert "init-db" in command_log
    assert "verify-secrets --all-storage" in command_log


def test_start_scripts_bind_to_lan_but_probe_and_open_loopback() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    python_source = (repository_root / "scripts" / "start.py").read_text(
        encoding="utf-8"
    )
    powershell_source = (repository_root / "scripts" / "start.ps1").read_text(
        encoding="utf-8"
    )

    assert '_BIND_HOST: Final = "0.0.0.0"' in python_source
    assert '_LOOPBACK_HOST: Final = "127.0.0.1"' in python_source
    assert '"--host",\n            _BIND_HOST' in python_source
    assert "lan-url:http://{socket.gethostname()}" in python_source
    assert '$BindAddress = "0.0.0.0"' in powershell_source
    assert '$LoopbackAddress = "127.0.0.1"' in powershell_source
    assert '"--host", $BindAddress' in powershell_source
    assert "lan-url:http://$($env:COMPUTERNAME)" in powershell_source

def _prepare_start_py_fixture(tmp_path: Path, dotenv_value: str) -> StartPyFixture:
    project_root = tmp_path / "project"
    script_directory = project_root / "scripts"
    fake_bin = tmp_path / "fake-bin"
    home = tmp_path / "provided-home"
    selection_marker = tmp_path / "selection.marker"
    command_log = tmp_path / "commands.log"
    script_directory.mkdir(parents=True)
    fake_bin.mkdir()

    repository_root = Path(__file__).resolve().parents[2]
    _ = shutil.copyfile(
        repository_root / "scripts" / "start.py",
        script_directory / "start.py",
    )
    _ = (project_root / ".env").write_text(
        f"G2B_SERVICE_KEY={dotenv_value}\n",
        encoding="ascii",
    )
    _ = (fake_bin / "g2b-compare.cmd").write_text(
        (
            """@echo off
echo %*>>"%G2B_COMMAND_LOG%"
if "%G2B_SERVICE_KEY%"=="%G2B_EXPECTED_SERVICE_KEY%" (
  echo selected>"%G2B_SELECTION_MARKER%"
) else (
  echo unexpected>"%G2B_SELECTION_MARKER%"
)
echo %* | findstr /C:"verify-secrets --all-storage" >nul
if errorlevel 1 goto done
if "%G2B_SIMULATE_VERIFY_FAILURE%"=="true" exit /b 1
:done
exit /b 0
"""
        ),
        encoding="ascii",
    )
    return StartPyFixture(
        project_root,
        fake_bin,
        home,
        selection_marker,
        command_log,
    )


def _launcher_environment(
    fixture: StartPyFixture,
    expected_service_key: str,
) -> dict[str, str]:
    environment = dict(os.environ)
    _ = environment.pop("G2B_SERVICE_KEY", None)
    _ = environment.pop("G2B_SIMULATE_VERIFY_FAILURE", None)
    environment["PATH"] = f"{fixture.fake_bin}{os.pathsep}{environment['PATH']}"
    environment["G2B_EXPECTED_SERVICE_KEY"] = expected_service_key
    environment["G2B_SELECTION_MARKER"] = str(fixture.selection_marker)
    environment["G2B_COMMAND_LOG"] = str(fixture.command_log)
    return environment


def _run_start_py(
    fixture: StartPyFixture,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        (
            sys.executable,
            str(fixture.project_root / "scripts" / "start.py"),
            "--provision-only",
            "--home",
            str(fixture.home),
        ),
        check=False,
        capture_output=True,
        cwd=fixture.project_root,
        env=environment,
        text=True,
    )
