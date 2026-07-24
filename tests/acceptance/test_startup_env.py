from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StartupFixture:
    project_root: Path
    fake_bin: Path
    home: Path
    selection_marker: Path
    ready_marker: Path


def test_start_script_loads_service_key_from_project_dotenv_when_process_key_missing(
    tmp_path: Path,
) -> None:
    # Given: an isolated project has only a dotenv service-key fixture.
    dotenv_service_key = "dotenv-fixture-value"
    fixture = _prepare_startup_fixture(tmp_path, dotenv_service_key)
    environment = _launcher_environment(fixture, dotenv_service_key)

    # When: provisioning runs through the copied launcher.
    completed = _run_start_script(fixture, environment)

    # Then: the fake child receives the dotenv-selected value.
    assert completed.returncode == 0
    assert fixture.selection_marker.read_text(encoding="ascii").strip() == "selected"


def test_start_script_keeps_nonblank_process_service_key_over_project_dotenv(
    tmp_path: Path,
) -> None:
    # Given: the process and dotenv values are distinct.
    dotenv_service_key = "dotenv-fixture-value"
    process_service_key = "process-fixture-value"
    fixture = _prepare_startup_fixture(tmp_path, dotenv_service_key)
    environment = _launcher_environment(fixture, process_service_key)
    environment["G2B_SERVICE_KEY"] = process_service_key

    # When: provisioning runs through the copied launcher.
    completed = _run_start_script(fixture, environment)

    # Then: the fake child receives only the process-selected value.
    assert completed.returncode == 0
    assert fixture.selection_marker.read_text(encoding="ascii").strip() == "selected"


def test_start_script_surfaces_known_sync_full_receipt_without_raw_child_output(
    tmp_path: Path,
) -> None:
    # Given: sync full emits a known blocked receipt plus a raw child canary.
    dotenv_service_key = "dotenv-fixture-value"
    raw_child_canary = "launcher-output-canary"
    fixture = _prepare_startup_fixture(tmp_path, dotenv_service_key)
    environment = _launcher_environment(fixture, dotenv_service_key)
    environment["G2B_SYNC_FULL_FAILURE"] = "true"
    environment["G2B_RAW_CHILD_CANARY"] = raw_child_canary

    # When: provisioning reaches the fake full-sync failure.
    completed = _run_start_script(fixture, environment)

    # Then: the safe receipt is reported without the raw child failure.
    launcher_output = completed.stdout + completed.stderr
    raw_child_canary_is_absent_from_stdout = raw_child_canary not in completed.stdout
    raw_child_canary_is_absent_from_stderr = raw_child_canary not in completed.stderr
    known_receipt_is_reported = "permanent-page-source-failure" in launcher_output
    assert completed.returncode != 0
    assert raw_child_canary_is_absent_from_stdout
    assert raw_child_canary_is_absent_from_stderr
    assert known_receipt_is_reported


def _prepare_startup_fixture(
    tmp_path: Path,
    dotenv_service_key: str,
) -> StartupFixture:
    project_root = tmp_path / "project"
    script_directory = project_root / "scripts"
    docs_directory = project_root / "docs"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    selection_marker = tmp_path / "selection.marker"
    ready_marker = tmp_path / "ready.marker"
    script_directory.mkdir(parents=True)
    docs_directory.mkdir(parents=True)
    fake_bin.mkdir()

    repository_root = Path(__file__).resolve().parents[2]
    _ = shutil.copyfile(
        repository_root / "scripts" / "start.ps1",
        script_directory / "start.ps1",
    )
    _ = shutil.copyfile(
        repository_root / "docs" / "api-contract-observed.json",
        docs_directory / "api-contract-observed.json",
    )
    _ = (project_root / ".env").write_text(
        f"G2B_SERVICE_KEY={dotenv_service_key}\n",
        encoding="ascii",
    )
    _ = (fake_bin / "uv.cmd").write_text(
        """@echo off
echo %* | findstr /C:" sync full" >nul
if errorlevel 1 goto command_status
if "%G2B_SERVICE_KEY%"=="%G2B_EXPECTED_SERVICE_KEY%" (
  echo selected>"%G2B_SELECTION_MARKER%"
) else (
  echo unexpected>"%G2B_SELECTION_MARKER%"
)
if "%G2B_SYNC_FULL_FAILURE%"=="true" (
  echo {"error":"permanent-page-source-failure","status":"blocked"} 1>&2
  echo malformed-raw-fake-child-failure %G2B_RAW_CHILD_CANARY% 1>&2
  exit /b 1
)
:command_status
echo %* | findstr /C:" precompute" >nul && echo ready>"%G2B_FAKE_READY%"
echo %* | findstr /C:" verify" >nul && if not exist "%G2B_FAKE_READY%" exit /b 1
exit /b 0
""",
        encoding="ascii",
    )
    return StartupFixture(
        project_root=project_root,
        fake_bin=fake_bin,
        home=home,
        selection_marker=selection_marker,
        ready_marker=ready_marker,
    )


def _launcher_environment(
    fixture: StartupFixture,
    expected_service_key: str,
) -> dict[str, str]:
    environment = dict(os.environ)
    _ = environment.pop("G2B_SERVICE_KEY", None)
    _ = environment.pop("G2B_RELATIONS_WORKBOOK", None)
    _ = environment.pop("G2B_SECRET_SOURCE", None)
    environment["PATH"] = f"{fixture.fake_bin}{os.pathsep}{environment['PATH']}"
    environment["G2B_EXPECTED_SERVICE_KEY"] = expected_service_key
    environment["G2B_SELECTION_MARKER"] = str(fixture.selection_marker)
    environment["G2B_FAKE_READY"] = str(fixture.ready_marker)
    return environment


def _run_start_script(
    fixture: StartupFixture,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return subprocess.run(  # noqa: S603
        (
            executable,
            "-NoProfile",
            "-File",
            str(fixture.project_root / "scripts" / "start.ps1"),
            "-HomePath",
            str(fixture.home),
            "-ProvisionOnly",
        ),
        check=False,
        capture_output=True,
        cwd=fixture.project_root,
        env=environment,
        text=True,
    )
