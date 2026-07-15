# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["openpyxl", "pydantic"]
# ///
# ─── How to run ───
# uv run tools/extract_workbook_fixtures.py \
#   --source-dir dataset --output-dir tests/fixtures

"""Extract deterministic sanitized fixtures from the three source workbooks."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.workbook_fixture.extract import (
    build_fixture_bundle,
    verify_manifest,
)
from tools.workbook_fixture.models import FixtureError
from tools.workbook_fixture.output import (
    validate_output_paths,
    write_json_atomic,
)

_OUTPUT_PATHS = (
    Path("workbooks/manifest-v1.json"),
    Path("normalization/workbook-smoke-v1.json"),
    Path("ranking/workbook-smoke-v1.json"),
)


class _CliArgs(argparse.Namespace):
    source_dir: Path = Path()
    output_dir: Path = Path()
    expected_manifest: Path | None = None
    verify_only: bool = False


def _parse_args() -> _CliArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--source-dir", required=True, type=Path)
    _ = parser.add_argument("--output-dir", required=True, type=Path)
    _ = parser.add_argument("--expected-manifest", type=Path)
    _ = parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args(namespace=_CliArgs())


def _run(args: _CliArgs) -> None:
    bundle = build_fixture_bundle(args.source_dir)
    if args.verify_only:
        if args.expected_manifest is None:
            message = "--verify-only requires --expected-manifest"
            raise FixtureError(message)
        verify_manifest(bundle.manifest, args.expected_manifest)
        return
    validate_output_paths(args.output_dir, _OUTPUT_PATHS)
    write_json_atomic(args.output_dir, _OUTPUT_PATHS[0], bundle.manifest)
    write_json_atomic(args.output_dir, _OUTPUT_PATHS[1], bundle.normalization)
    write_json_atomic(args.output_dir, _OUTPUT_PATHS[2], bundle.ranking)


def _main() -> int:
    try:
        _run(_parse_args())
    except (
        FixtureError,
        OSError,
        KeyError,
        ValueError,
        zipfile.BadZipFile,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
