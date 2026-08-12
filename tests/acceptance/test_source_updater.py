from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_updater_skips_current_version(tmp_path: Path) -> None:
    project = _prepare_project(tmp_path, "1.0.0")
    release = _prepare_release(tmp_path, "1.0.0")
    before = _snapshot(project)

    result = _run_updater(project, release)

    assert result.returncode == 0
    assert b"update-result:skipped:current=1.0.0,remote=1.0.0" in result.stdout
    assert _snapshot(project) == before


def test_source_updater_applies_newer_runtime_and_preserves_user_data(
    tmp_path: Path,
) -> None:
    project = _prepare_project(tmp_path, "1.0.9")
    release = _prepare_release(tmp_path, "1.0.10")
    dotenv = (project / ".env").read_bytes()
    database = (project / ".g2b" / "g2b.sqlite3").read_bytes()

    result = _run_updater(project, release)

    assert result.returncode == 0
    assert b"update-result:applied:1.0.10" in result.stdout
    assert (project / "APP_VERSION.txt").read_text(encoding="ascii") == "1.0.10\n"
    assert (
        project / "src" / "g2b_compare" / "updated.txt"
    ).read_text(encoding="utf-8") == "1.0.10"
    assert (project / "scripts" / "start-user.ps1").read_text(
        encoding="utf-8"
    ) == "# updated 1.0.10\n"
    assert (project / ".env").read_bytes() == dotenv
    assert (project / ".g2b" / "g2b.sqlite3").read_bytes() == database


def test_source_updater_fails_open_when_release_source_is_unavailable(
    tmp_path: Path,
) -> None:
    project = _prepare_project(tmp_path, "1.0.0")
    before = _snapshot(project)

    result = _run_updater(project, tmp_path / "missing-release")

    assert result.returncode == 0
    assert b"update-result:offline" in result.stdout
    assert _snapshot(project) == before


def _prepare_project(tmp_path: Path, version: str) -> Path:
    project = tmp_path / "project"
    _ = (project / "scripts").mkdir(parents=True)
    _ = (project / "src" / "g2b_compare" / "web" / "frontend_dist").mkdir(
        parents=True
    )
    _ = (project / ".g2b").mkdir()
    _ = shutil.copy2(
        PROJECT_ROOT / "scripts" / "start-user.ps1",
        project / "scripts" / "start-user.ps1",
    )
    _ = (project / "APP_VERSION.txt").write_text(f"{version}\n", encoding="ascii")
    _ = (project / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n',
        encoding="utf-8",
    )
    _ = (project / "uv.lock").write_text("fixture\n", encoding="utf-8")
    _ = (project / "scripts" / "start.py").write_text("# old\n", encoding="utf-8")
    _ = (project / "src" / "g2b_compare" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    frontend_index = (
        project
        / "src"
        / "g2b_compare"
        / "web"
        / "frontend_dist"
        / "index.html"
    )
    _ = frontend_index.write_text(
        "old",
        encoding="utf-8",
    )
    _ = (project / ".env").write_bytes(b"G2B_SERVICE_KEY=preserve-me\n")
    _ = (project / ".g2b" / "g2b.sqlite3").write_bytes(b"SQLite fixture")
    return project


def _prepare_release(tmp_path: Path, version: str) -> Path:
    release = tmp_path / f"release-{version}"
    release.mkdir()
    _ = (release / "APP_VERSION.txt").write_text(
        f"{version}\n",
        encoding="ascii",
    )
    archive = release / "source.zip"
    prefix = "g2b-compare-main"
    with zipfile.ZipFile(archive, "w") as bundle:
        files = {
            "APP_VERSION.txt": f"{version}\n",
            "pyproject.toml": f'[project]\nversion = "{version}"\n',
            "uv.lock": "fixture updated\n",
            "scripts/start.py": "# updated\n",
            "scripts/start-user.ps1": f"# updated {version}\n",
            "src/g2b_compare/__init__.py": "",
            "src/g2b_compare/updated.txt": version,
            "src/g2b_compare/web/frontend_dist/index.html": "updated",
            ".env": "G2B_SERVICE_KEY=poison\n",
            ".g2b/g2b.sqlite3": "poison",
        }
        for relative, content in files.items():
            bundle.writestr(f"{prefix}/{relative}", content.encode())
    return release


def _run_updater(project: Path, release: Path) -> subprocess.CompletedProcess[bytes]:
    powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return subprocess.run(  # noqa: S603
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project / "scripts" / "start-user.ps1"),
            "-CheckOnly",
            "-UpdateSource",
            str(release),
        ],
        cwd=project,
        check=False,
        capture_output=True,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
