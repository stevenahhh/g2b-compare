"""Build a clean source handoff ZIP for a non-Git distribution."""

from __future__ import annotations

import argparse
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Final, cast

ARCHIVE_ROOT: Final = "g2b-compare"
INCLUDED_ROOT_FILES: Final = {
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    "AGENTS.md",
    "APP_VERSION.txt",
    "CHANGELOG.md",
    "QUICK_START.txt",
    "README.md",
    "START_APP.bat",
    "pyproject.toml",
    "uv.lock",
}
INCLUDED_ROOTS: Final = {
    "docs",
    "electron-estimator",
    "frontend",
    "scripts",
    "src",
    "tests",
    "tools",
    "typings",
}
EXCLUDED_DIRECTORIES: Final = {
    ".basedpyright",
    ".cache",
    ".codex-tmp",
    ".codegraph",
    ".git",
    ".g2b",
    ".gjc",
    ".hypothesis",
    ".mypy_cache",
    ".omo",
    ".playwright",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".serena",
    ".uv-cache",
    ".uv-cache-env-loading",
    ".venv",
    "__pycache__",
    "_backup",
    "browser-temp",
    "build",
    "data",
    "dataset",
    "dist",
    "evidence-temp",
    "node_modules",
    "output",
    "outputs",
    "playwright-report",
    "qa-r2",
    "release",
    "test-results",
    "tmp",
    "var",
}
ROOT_ONLY_EXCLUDED_DIRECTORIES: Final = {
    "data",
    "dataset",
    "output",
    "outputs",
    "release",
    "tmp",
    "var",
}
EXCLUDED_SUFFIXES: Final = {
    ".asd",
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".wbk",
}
EXCLUDED_DOCUMENT_SUFFIXES: Final = {
    ".doc",
    ".docx",
    ".pdf",
    ".xls",
    ".xlsm",
    ".xlsx",
}
SECRET_PATTERN: Final = re.compile(
    b"|".join(
        (
            rb"gho_[A-Za-z0-9_]{20,}",
            rb"github_pat_[A-Za-z0-9_]{20,}",
            rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        )
    )
)
MAX_SECRET_SCAN_BYTES: Final = 5_000_000


class Arguments(argparse.Namespace):
    """Parsed package builder arguments."""

    project_root: Path = Path.cwd()
    output: Path = Path()
    include_env: bool = False
    include_runtime_data: bool = False


def should_include(
    relative: Path,
    *,
    include_env: bool,
    include_runtime_data: bool,
) -> bool:
    """Return whether a relative project path belongs in the package."""
    if relative.parts[0] == ".g2b" and include_runtime_data:
        return _should_include_runtime_data(relative)
    nested_exclusions = EXCLUDED_DIRECTORIES - ROOT_ONLY_EXCLUDED_DIRECTORIES
    if (
        relative.parts[0] in ROOT_ONLY_EXCLUDED_DIRECTORIES
        or any(part in nested_exclusions for part in relative.parts[:-1])
    ):
        return False
    if relative == Path(".env"):
        return include_env
    if relative.name.startswith(".env."):
        return relative.name == ".env.example"
    if len(relative.parts) == 1:
        return relative.name in INCLUDED_ROOT_FILES
    return (
        relative.parts[0] in INCLUDED_ROOTS
        and relative.suffix.lower() not in EXCLUDED_SUFFIXES
        and not (
            relative.parts[0] == "docs"
            and relative.suffix.lower() in EXCLUDED_DOCUMENT_SUFFIXES
        )
        and not relative.name.startswith("~$")
    )


def _should_include_runtime_data(relative: Path) -> bool:
    """Select only runtime state required for immediate application use."""
    if relative == Path(".g2b/g2b.sqlite3"):
        return True
    if len(relative.parts) > 1 and relative.parts[1] in {"raw", "samples", "docs"}:
        return relative.suffix.lower() not in {".log", ".tmp"}
    return False


def package_files(
    project_root: Path,
    *,
    include_env: bool,
    include_runtime_data: bool,
) -> list[Path]:
    """Select source and handoff files while excluding generated state."""
    selected: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if should_include(
            relative,
            include_env=include_env,
            include_runtime_data=include_runtime_data,
        ):
            selected.append(path)
    return sorted(selected, key=lambda item: item.as_posix().lower())


def scan_unexpected_secrets(project_root: Path, files: list[Path]) -> None:
    """Reject recognized credentials outside the explicitly included .env."""
    for path in files:
        if path.relative_to(project_root) == Path(".env"):
            continue
        if path.stat().st_size > MAX_SECRET_SCAN_BYTES:
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            message = f"cannot read package input: {path}"
            raise RuntimeError(message) from error
        if SECRET_PATTERN.search(data):
            message = f"unexpected credential pattern: {path}"
            raise RuntimeError(message)


def build_archive(
    project_root: Path,
    output: Path,
    *,
    include_env: bool,
    include_runtime_data: bool,
) -> None:
    """Create the deterministic handoff archive."""
    files = package_files(
        project_root,
        include_env=include_env,
        include_runtime_data=include_runtime_data,
    )
    scan_unexpected_secrets(project_root, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    database_path = project_root / ".g2b" / "g2b.sqlite3"
    with tempfile.TemporaryDirectory() as temporary_directory:
        snapshot_path = Path(temporary_directory) / "g2b.sqlite3"
        if include_runtime_data:
            snapshot_database(database_path, snapshot_path)
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in files:
                relative = path.relative_to(project_root).as_posix()
                archive_path = f"{ARCHIVE_ROOT}/{relative}"
                if path == database_path:
                    archive.write(snapshot_path, archive_path)
                else:
                    archive.write(path, archive_path)


def snapshot_database(source: Path, destination: Path) -> None:
    """Create a transactionally consistent SQLite backup for handoff."""
    if not source.is_file():
        message = f"runtime database is missing: {source}"
        raise FileNotFoundError(message)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        integrity_row = cast(
            "tuple[str] | None",
            destination_connection.execute("PRAGMA integrity_check").fetchone(),
        )
        if integrity_row != ("ok",):
            message = (
                "runtime database backup failed integrity check: "
                f"{integrity_row}"
            )
            raise RuntimeError(message)
    finally:
        destination_connection.close()
        source_connection.close()


def main() -> None:
    """Parse CLI arguments and build the source handoff ZIP."""
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--project-root", type=Path, default=Path.cwd())
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument("--include-env", action="store_true")
    _ = parser.add_argument("--include-runtime-data", action="store_true")
    arguments = Arguments()
    _ = parser.parse_args(namespace=arguments)
    root = arguments.project_root.resolve()
    output = arguments.output.resolve()
    build_archive(
        root,
        output,
        include_env=arguments.include_env,
        include_runtime_data=arguments.include_runtime_data,
    )
    print(output)


if __name__ == "__main__":
    main()
