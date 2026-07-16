# How to run: uv run tools/diagnose_g2b_limit.py --secret-source PATH

"""Run the one-call sanitized G2B provider-limit diagnostic."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from g2b_compare.contracts.diagnostic import (
    LimitDiagnosticConfig,
    run_limit_diagnostic,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_OUTPUT = Path(".omo/evidence/task-2-contract/limit-diagnostic.json")
DEFAULT_LEDGER = Path("var/contract-capture.sqlite3")
DEFAULT_QUOTA = Path("docs/account-quota-observed.json")


class _Args(argparse.Namespace):
    """Typed mutable namespace populated by argparse."""

    def __init__(self) -> None:
        super().__init__()
        self.secret_source: Path = Path()
        self.ledger: Path = DEFAULT_LEDGER
        self.quota: Path = DEFAULT_QUOTA
        self.output: Path = DEFAULT_OUTPUT


def main(argv: Sequence[str] | None = None) -> int:
    """Run the executable one-call diagnostic mode."""
    parser = argparse.ArgumentParser(
        description=(
            "Make exactly one sanitized MAS D3 numOfRows=1000 diagnostic request."
        )
    )
    _ = parser.add_argument("--secret-source", type=Path, required=True)
    _ = parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    _ = parser.add_argument("--quota", type=Path, default=DEFAULT_QUOTA)
    _ = parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv, namespace=_Args())
    result = run_limit_diagnostic(
        LimitDiagnosticConfig(
            output_path=args.output,
            ledger_path=args.ledger,
            quota_path=args.quota,
            secret_source=args.secret_source,
            observed_at=datetime.now(UTC),
        )
    )
    _ = sys.stdout.write(result.model_dump_json() + "\n")
    return 0

raise SystemExit(main())
