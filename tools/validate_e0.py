"""Command-line validation for external E0 assessment packages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from g2b_compare.errors import G2BCompareError
from g2b_compare.evaluation.e0_schema import validate_e0_package


def build_parser() -> argparse.ArgumentParser:
    """Build the public E0 validation command interface."""
    parser = argparse.ArgumentParser(
        description="Validate an immutable external E0 assessment package.",
    )
    parser.add_argument(
        "manifest",
        type=Path,
        help="Path to the E0 manifest JSON file.",
    )
    return parser


def main() -> int:
    """Validate one manifest and return a process exit code."""
    build_parser().parse_args()
    manifest_path = Path(sys.argv[-1])
    try:
        report = validate_e0_package(manifest_path)
    except G2BCompareError as error:
        print(f"E0 검증 실패: {error}")
        return 2
    print(
        f"E0 검증 완료: records={report.total_count} files={report.file_count}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
