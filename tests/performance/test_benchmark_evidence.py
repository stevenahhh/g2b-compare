"""Machine benchmark evidence schema contract."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue
from g2b_compare.evaluation.benchmark import (
    BenchmarkEvidence,
    BenchmarkPlan,
    benchmark_operation,
    write_benchmark_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


def test_machine_evidence_records_every_required_reproduction_field(
    tmp_path: Path,
) -> None:
    def operation() -> None:
        return

    result = benchmark_operation(
        BenchmarkPlan("search", 1, 2, timedelta(seconds=1)),
        operation,
    )
    evidence = BenchmarkEvidence(
        corpus_sha256="a" * 64,
        query_sha256="b" * 64,
        database_sha256="c" * 64,
        index_sha256="d" * 64,
        cache_sha256="e" * 64,
        thread_variables=(
            ("PYTHONHASHSEED", "0"),
            ("OMP_NUM_THREADS", "1"),
            ("MKL_NUM_THREADS", "1"),
            ("OPENBLAS_NUM_THREADS", "1"),
        ),
        request_mix=(("search", 200), ("cache-hit", 200)),
        cache_policy=(
            ("comparator-result-cache-hit-lane", True),
            ("comparator-result-cache-search-lane", False),
            ("pair-feature-memoization", "exact-pure-lru"),
            ("pair-feature-memoization-maxsize", 150_000),
        ),
        process_modes=("process-cold", "warm-OS-cache"),
        results=(result,),
    )
    path = tmp_path / "benchmark.json"

    write_benchmark_evidence(path, evidence)
    payload = JSON_ADAPTER.validate_json(path.read_bytes())

    assert payload["percentile_method"] == "nearest-rank"
    assert payload["process_modes"] == ["process-cold", "warm-OS-cache"]
    assert payload["cache_policy"] == {
        "comparator-result-cache-hit-lane": True,
        "comparator-result-cache-search-lane": False,
        "pair-feature-memoization": "exact-pure-lru",
        "pair-feature-memoization-maxsize": 150_000,
    }
    assert payload["artifacts"] == {
        "cache_sha256": "e" * 64,
        "corpus_sha256": "a" * 64,
        "database_sha256": "c" * 64,
        "index_sha256": "d" * 64,
        "query_sha256": "b" * 64,
    }
