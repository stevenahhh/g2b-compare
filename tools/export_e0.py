#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["g2b-compare"]
# ///

# ─── How to run ───
# 1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
# 2. Run: uv run tools/export_e0.py --release-bundle ID --out PATH
# ──────────────────

"""Export an immutable unlabeled E0 package from the active frozen release."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from g2b_compare.evaluation.e0_export import E0ExportBlocked, export_e0
from g2b_compare.evaluation.e0_reader import read_frozen_e0_release
from g2b_compare.services.release import open_release_reader, pin_active_release
from g2b_compare.services.release_models import ReleaseContractError, ReleasePin

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_DATABASE = Path("var/g2b.sqlite3")
DEFAULT_SEED = "20260714"


class ExportNamespace(argparse.Namespace):
    """Typed mutable target populated by argparse."""

    database: Path
    release_bundle: int
    out: Path
    seed: str

    def __init__(self) -> None:
        """Initialize parser defaults before required values are overwritten."""
        super().__init__()
        self.database = DEFAULT_DATABASE
        self.release_bundle = 0
        self.out = Path()
        self.seed = DEFAULT_SEED


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic E0 export command interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    _ = parser.add_argument("--release-bundle", type=int, required=True)
    _ = parser.add_argument("--out", type=Path, required=True)
    _ = parser.add_argument("--seed", default=DEFAULT_SEED)
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> ExportNamespace:
    """Parse CLI tokens into a typed namespace."""
    namespace = ExportNamespace()
    _ = build_parser().parse_args(argv, namespace=namespace)
    return namespace


def main(argv: Sequence[str] | None = None) -> int:
    """Export one pinned package with stable success, blocked, and I/O exits."""
    args = parse_arguments(argv)
    try:
        pin = pin_active_release(args.database)
        _require_bundle(pin, args.release_bundle)
        with open_release_reader(args.database, pin) as connection:
            release = read_frozen_e0_release(connection, pin)
        report = export_e0(
            release,
            args.out,
            seed=args.seed,
            expected_bundle_sha=release.identity.release_bundle_sha,
        )
    except (E0ExportBlocked, ReleaseContractError) as error:
        print(f"E0 BLOCKED: {error}")
        return 2
    except (OSError, sqlite3.DatabaseError) as error:
        print(f"E0 I/O ERROR: {error}")
        return 3
    summary = " ".join(
        (
            f"anchors={report.anchor_count}",
            f"pairs={report.pair_count}",
            f"parser_rows={report.parser_row_count}",
            f"manifest={report.manifest_sha256}",
        )
    )
    print(f"E0 EXPORTED: {summary}")
    return 0


def _require_bundle(pin: ReleasePin, requested_bundle_id: int) -> None:
    if pin.bundle_id != requested_bundle_id:
        detail = "requested bundle is not the active frozen release"
        raise E0ExportBlocked(detail)


if __name__ == "__main__":
    raise SystemExit(main())
