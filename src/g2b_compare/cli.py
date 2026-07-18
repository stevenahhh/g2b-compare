"""Installed command-line boundary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from g2b_compare.observability.cli_actions import dispatch, emit, error
from g2b_compare.observability.cli_args import Args, parser, runtime_paths
from g2b_compare.observability.runtime_ops import RuntimeOperationError
from g2b_compare.observability.secrets import SecretScanError

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, authorize, and dispatch one local operation."""
    try:
        args = Args.model_validate(vars(parser().parse_args(argv)))
        if (
            args.command == "sync"
            and not args.dry_run
            and not os.getenv("G2B_SERVICE_KEY")
        ):
            return error("missing-service-key", 2)
        if args.dry_run:
            return emit({"command": args.command, "status": "dry-run"})
        return dispatch(args, runtime_paths(args))
    except (OSError, RuntimeOperationError, SecretScanError, ValueError) as caught:
        return error(str(caught), 1)


__all__ = ["main", "parser"]
