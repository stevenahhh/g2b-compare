"""Typed command grammar and runtime path resolution."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel

LOOPBACK: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Resolved local runtime artifacts."""

    home: Path
    database: Path
    index: Path
    contract: Path


class Args(BaseModel):
    """Parsed and typed command inputs."""

    home: Path
    database: Path | None = None
    index: Path | None = None
    contract: Path | None = None
    command: str
    dry_run: bool = False
    before: str = ""
    mode: str = ""
    host: str = LOOPBACK
    port: int = DEFAULT_PORT
    all_storage: bool = False
    max_batches: int = 1


def parser() -> argparse.ArgumentParser:
    """Build the complete installed command grammar."""
    root = argparse.ArgumentParser(prog="g2b-compare")
    _ = root.add_argument("--home", type=Path, default=Path(os.getenv("G2B_HOME", ".")))
    _ = root.add_argument("--database", type=Path)
    _ = root.add_argument("--index", type=Path)
    _ = root.add_argument("--contract", type=Path)
    commands = root.add_subparsers(dest="command", required=True)
    for name in (
        "init-db",
        "capture-contract",
        "import-relations",
        "materialize",
        "rebuild-index",
        "precompute",
        "verify",
        "coverage-stats",
        "prune-raw",
    ):
        _ = commands.add_parser(name).add_argument("--dry-run", action="store_true")
    secrets = commands.add_parser("verify-secrets")
    _ = secrets.add_argument("--all-storage", action="store_true")
    _ = secrets.add_argument("--dry-run", action="store_true")
    sync = commands.add_parser("sync")
    _ = sync.add_argument("mode", choices=("full", "delta", "attributes"))
    _ = sync.add_argument("--max-batches", type=int, default=1)
    _ = sync.add_argument("--dry-run", action="store_true")
    prune = commands.choices["prune-raw"]
    _ = prune.add_argument("--before", default="1970-01-01T00:00:00Z")
    serve = commands.add_parser("serve")
    _ = serve.add_argument("--host", default=LOOPBACK)
    _ = serve.add_argument("--port", default=DEFAULT_PORT, type=int)
    _ = serve.add_argument("--dry-run", action="store_true")
    return root


def runtime_paths(args: Args) -> RuntimePaths:
    """Resolve mandatory runtime artifacts under the selected home."""
    home = args.home.resolve()
    return RuntimePaths(
        home,
        (args.database or home / "g2b.sqlite3").resolve(),
        (args.index or home / "search-index.bin").resolve(),
        (args.contract or home / "docs" / "api-contract-observed.json").resolve(),
    )
