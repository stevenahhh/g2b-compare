"""Build a clean source handoff ZIP for a non-Git distribution."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from typing import Final

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


def should_include(relative: Path, *, include_env: bool) -> bool:
    """Return whether a relative project path belongs in the package."""
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts[:-1]):
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


def package_files(project_root: Path, *, include_env: bool) -> list[Path]:
    """Select source and handoff files while excluding generated state."""
    selected: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root)
        if should_include(relative, include_env=include_env):
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


def build_archive(project_root: Path, output: Path, *, include_env: bool) -> None:
    """Create the deterministic handoff archive."""
    files = package_files(project_root, include_env=include_env)
    scan_unexpected_secrets(project_root, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(project_root).as_posix()
            archive.write(path, f"{ARCHIVE_ROOT}/{relative}")


def main() -> None:
    """Parse CLI arguments and build the source handoff ZIP."""
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--project-root", type=Path, default=Path.cwd())
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument("--include-env", action="store_true")
    arguments = Arguments()
    _ = parser.parse_args(namespace=arguments)
    root = arguments.project_root.resolve()
    output = arguments.output.resolve()
    build_archive(root, output, include_env=arguments.include_env)
    print(output)


if __name__ == "__main__":
    main()
