from __future__ import annotations

import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_handoff_package_keeps_sources_and_env_but_excludes_runtime(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    output = tmp_path / "handoff.zip"
    _write_fixture(project)

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "build_handoff_package.py"),
            "--project-root",
            str(project),
            "--output",
            str(output),
            "--include-env",
            "--include-runtime-data",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "g2b-compare/START_APP.bat" in names
        assert "g2b-compare/.env" in names
        assert "g2b-compare/.g2b/g2b.sqlite3" in names
        assert "g2b-compare/.g2b/raw/sha256/aa/payload.bin.gz" in names
        assert "g2b-compare/.g2b/docs/api-contract-observed.json" in names
        assert "g2b-compare/src/g2b_compare/app.py" in names
        assert "g2b-compare/src/g2b_compare/normalize/data/units-v2.json" in names
        assert "g2b-compare/frontend/src/App.svelte" in names
        assert "g2b-compare/electron-estimator/src/main/index.ts" in names
        assert "g2b-compare/tests/test_app.py" in names
        assert "g2b-compare/docs/guide.md" in names
        assert "g2b-compare/.g2b/server.log" not in names
        assert "g2b-compare/.g2b/exports/old.xlsx" not in names
        assert "g2b-compare/.g2b/g2b-runtime.sqlite3" not in names
        assert "g2b-compare/frontend/node_modules/pkg/index.js" not in names
        assert "g2b-compare/electron-estimator/dist/main.js" not in names
        assert "g2b-compare/docs/report.docx" not in names
        assert "g2b-compare/.git/config" not in names
        database_bytes = archive.read("g2b-compare/.g2b/g2b.sqlite3")
        extracted_database = tmp_path / "database.sqlite3"
        _ = extracted_database.write_bytes(database_bytes)
        connection = sqlite3.connect(extracted_database)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT value FROM items").fetchone() == (
                "latest",
            )
        finally:
            connection.close()


def _write_fixture(project: Path) -> None:
    files = {
        "START_APP.bat": "@echo off\n",
        "APP_VERSION.txt": "0.2.0\n",
        "pyproject.toml": '[project]\nversion = "0.2.0"\n',
        "uv.lock": "fixture\n",
        ".env": "G2B_SERVICE_KEY=fixture-secret\n",
        "src/g2b_compare/app.py": "APP = True\n",
        "src/g2b_compare/normalize/data/units-v2.json": "{}\n",
        "frontend/src/App.svelte": "<main />\n",
        "frontend/node_modules/pkg/index.js": "generated\n",
        "electron-estimator/src/main/index.ts": "export {};\n",
        "electron-estimator/dist/main.js": "generated\n",
        "tests/test_app.py": "def test_app(): assert True\n",
        "docs/guide.md": "# Guide\n",
        "docs/report.docx": "generated report\n",
        ".g2b/g2b-runtime.sqlite3": "old runtime\n",
        ".g2b/raw/sha256/aa/payload.bin.gz": "raw\n",
        ".g2b/docs/api-contract-observed.json": "{}\n",
        ".g2b/exports/old.xlsx": "old export\n",
        ".g2b/server.log": "log\n",
        ".git/config": "git\n",
    }
    for relative, content in files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8")
    database = project / ".g2b" / "g2b.sqlite3"
    connection = sqlite3.connect(database)
    try:
        _ = connection.execute("CREATE TABLE items (value TEXT NOT NULL)")
        _ = connection.execute("INSERT INTO items VALUES ('latest')")
        connection.commit()
    finally:
        connection.close()
