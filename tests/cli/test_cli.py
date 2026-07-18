from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.cli import main, parser

if TYPE_CHECKING:
    from pathlib import Path


def test_all_commands_expose_help() -> None:
    help_text = parser().format_help()
    commands = {
        "init-db",
        "capture-contract",
        "sync",
        "import-relations",
        "rebuild-index",
        "precompute",
        "verify",
        "verify-secrets",
        "prune-raw",
        "serve",
    }
    assert all(command in help_text for command in commands)


def test_init_db_and_dry_run(tmp_path: Path) -> None:
    assert main(("--home", str(tmp_path), "init-db")) == 0
    assert (tmp_path / "g2b.sqlite3").is_file()
    assert main(("--home", str(tmp_path), "sync", "full", "--dry-run")) == 0


def test_public_bind_fails_closed() -> None:
    public_host = "0.0.0.0"  # noqa: S104
    assert main(("serve", "--host", public_host)) == 2
