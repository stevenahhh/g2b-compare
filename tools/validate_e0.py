"""Command-line validation for external E0 assessment packages."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from g2b_compare.errors import G2BCompareError
from g2b_compare.evaluation.e0_schema import validate_e0_package

if TYPE_CHECKING:
    from collections.abc import Sequence


class ValidationNamespace(argparse.Namespace):
    """Typed mutable argparse target for strict validation."""

    manifest: Path
    source_export: Path | None
    strict: bool

    def __init__(self) -> None:
        """Initialize defaults before argparse overwrites required fields."""
        super().__init__()
        self.manifest = Path()
        self.source_export = None
        self.strict = False


def build_parser() -> argparse.ArgumentParser:
    """Build the public E0 validation command interface."""
    parser = argparse.ArgumentParser(
        description="Validate an immutable external E0 assessment package.",
    )
    _ = parser.add_argument(
        "manifest",
        type=Path,
        help="Path to the E0 manifest JSON file.",
    )
    _ = parser.add_argument(
        "--strict",
        action="store_true",
        help="Require a complete e0-strict-v1 external gold package.",
    )
    _ = parser.add_argument(
        "--source-export",
        type=Path,
        help="Path to the exact e0-export-v1 manifest required by --strict.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one manifest and return a process exit code."""
    namespace = ValidationNamespace()
    _ = build_parser().parse_args(argv, namespace=namespace)
    try:
        report = validate_e0_package(
            namespace.manifest,
            strict=namespace.strict,
            source_export=namespace.source_export,
        )
    except G2BCompareError as error:
        print(f"E0 검증 실패: {error}")
        return 2
    print(
        f"E0 검증 완료: records={report.total_count} files={report.file_count}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
