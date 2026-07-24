"""CLI for deterministic perf-v1 corpus publication."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.evaluation.perf_corpus import PerfCorpusResult, generate_perf_corpus

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class Arguments:
    """Typed CLI boundary for a new output directory."""

    output: Path


class _Namespace(argparse.Namespace):
    out: Path = Path()


def parse_arguments(argv: Sequence[str] | None = None) -> Arguments:
    """Parse the required immutable output directory."""
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--out", type=Path, required=True)
    parsed = _Namespace()
    _ = parser.parse_args(argv, namespace=parsed)
    return Arguments(parsed.out)


def main(argv: Sequence[str] | None = None) -> int:
    """Generate once and print a secret-free machine receipt."""
    arguments = parse_arguments(argv)
    try:
        result = generate_perf_corpus(arguments.output)
    except OSError:
        return 2
    _ = sys.stdout.write(canonical_json(_receipt(result)) + "\n")
    return 0


def _receipt(result: PerfCorpusResult) -> dict[str, JsonValue]:
    return {
        "cache_sha256": result.cache_sha256,
        "corpus_sha256": result.corpus_sha256,
        "database_sha256": result.database_sha256,
        "char_idf_sha256": result.char_idf_sha256,
        "char_index_sha256": result.char_index_sha256,
        "index_sha256": result.index_sha256,
        "index_manifest_sha256": result.index_manifest_sha256,
        "missing_price_count": result.missing_price_count,
        "mixed_unit_count": result.mixed_unit_count,
        "product_count": result.product_count,
        "query_count": result.query_count,
        "query_sha256": result.query_sha256,
        "query_with_price_count": result.query_with_price_count,
        "query_with_spec_count": result.query_with_spec_count,
        "structured_count": result.structured_count,
        "word_idf_sha256": result.word_idf_sha256,
        "word_index_sha256": result.word_index_sha256,
    }


if __name__ == "__main__":
    raise SystemExit(main())
