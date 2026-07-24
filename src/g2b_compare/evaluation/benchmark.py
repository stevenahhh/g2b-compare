"""Deterministic nearest-rank timing statistics for local release gates."""

from __future__ import annotations

import math
import platform
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final, override

from g2b_compare.db.hashes import JsonValue, canonical_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta
    from pathlib import Path

NANOSECONDS_PER_MILLISECOND: Final = Decimal(1_000_000)
EMPTY_SAMPLES: Final = "empty-samples"


@final
class BenchmarkThresholdError(Exception):
    """Name a benchmark whose measured p95 exceeds its release budget."""

    __slots__: tuple[str, ...] = ("benchmark", "p95_ms", "threshold_ms")
    benchmark: str
    p95_ms: Decimal
    threshold_ms: Decimal

    def __init__(
        self,
        benchmark: str,
        p95_ms: Decimal,
        threshold_ms: Decimal,
    ) -> None:
        """Retain exact measured and allowed timings."""
        super().__init__(benchmark, p95_ms, threshold_ms)
        self.benchmark = benchmark
        self.p95_ms = p95_ms
        self.threshold_ms = threshold_ms

    @override
    def __str__(self) -> str:
        return f"{self.benchmark}: p95={self.p95_ms}ms threshold={self.threshold_ms}ms"


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Machine-serializable summary for one benchmark scenario."""

    name: str
    warmups: int
    repetitions: int
    percentile_method: str
    p50_ms: Decimal
    p95_ms: Decimal
    max_ms: Decimal
    threshold_ms: Decimal


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    """Artifact identities, environment, request mix, and measured scenarios."""

    corpus_sha256: str
    query_sha256: str
    database_sha256: str
    index_sha256: str
    cache_sha256: str
    thread_variables: tuple[tuple[str, str], ...]
    request_mix: tuple[tuple[str, int], ...]
    cache_policy: tuple[tuple[str, str | int | bool], ...]
    process_modes: tuple[str, ...]
    results: tuple[BenchmarkResult, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkPlan:
    """Stable scenario identity, sample counts, and release budget."""

    name: str
    warmups: int
    repetitions: int
    threshold: timedelta


def nearest_rank_percentile(
    values: tuple[int, ...],
    percentile: Decimal,
) -> int:
    """Return a non-interpolated nearest-rank percentile."""
    if not values:
        raise BenchmarkThresholdError(EMPTY_SAMPLES, Decimal(0), Decimal(0))
    rank = math.ceil(float(percentile * len(values)))
    return sorted(values)[max(1, rank) - 1]


def benchmark_operation(
    plan: BenchmarkPlan,
    operation: Callable[[], None],
    *,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> BenchmarkResult:
    """Measure one serial operation and enforce its nearest-rank p95."""
    for _ in range(plan.warmups):
        operation()
    samples: list[int] = []
    for _ in range(plan.repetitions):
        started = clock_ns()
        operation()
        samples.append(clock_ns() - started)
    return summarize_samples(plan, tuple(samples))


def summarize_samples(
    plan: BenchmarkPlan,
    samples_ns: tuple[int, ...],
) -> BenchmarkResult:
    """Summarize externally captured serial timings with the same release rule."""
    if len(samples_ns) != plan.repetitions:
        raise BenchmarkThresholdError(
            plan.name,
            Decimal(len(samples_ns)),
            Decimal(plan.repetitions),
        )
    values = samples_ns
    p50 = _milliseconds(nearest_rank_percentile(values, Decimal("0.50")))
    p95 = _milliseconds(nearest_rank_percentile(values, Decimal("0.95")))
    maximum = _milliseconds(max(values))
    threshold_ms = Decimal(str(plan.threshold.total_seconds() * 1_000))
    if p95 > threshold_ms:
        raise BenchmarkThresholdError(plan.name, p95, threshold_ms)
    return BenchmarkResult(
        plan.name,
        plan.warmups,
        plan.repetitions,
        "nearest-rank",
        p50,
        p95,
        maximum,
        threshold_ms,
    )


def write_benchmark_evidence(path: Path, evidence: BenchmarkEvidence) -> None:
    """Write one canonical machine JSON receipt with no timing interpolation."""
    request_mix = _json_mapping(evidence.request_mix)
    thread_variables = _json_mapping(evidence.thread_variables)
    cache_policy = _json_mapping(evidence.cache_policy)
    payload: dict[str, JsonValue] = {
        "artifacts": {
            "cache_sha256": evidence.cache_sha256,
            "corpus_sha256": evidence.corpus_sha256,
            "database_sha256": evidence.database_sha256,
            "index_sha256": evidence.index_sha256,
            "query_sha256": evidence.query_sha256,
        },
        "cache_policy": cache_policy,
        "environment": {
            "machine": platform.machine(),
            "python": platform.python_version(),
            "system": platform.system(),
        },
        "percentile_method": "nearest-rank",
        "process_modes": list(evidence.process_modes),
        "request_mix": request_mix,
        "results": [_result_payload(result) for result in evidence.results],
        "schema_version": "perf-benchmark-v1",
        "thread_variables": thread_variables,
    }
    _ = path.write_text(canonical_json(payload) + "\n", encoding="utf-8", newline="\n")


def _result_payload(result: BenchmarkResult) -> dict[str, JsonValue]:
    return {
        "max_ms": str(result.max_ms),
        "name": result.name,
        "p50_ms": str(result.p50_ms),
        "p95_ms": str(result.p95_ms),
        "percentile_method": result.percentile_method,
        "repetitions": result.repetitions,
        "threshold_ms": str(result.threshold_ms),
        "warmups": result.warmups,
    }


def _json_mapping(
    rows: tuple[tuple[str, str | int | bool], ...],
) -> dict[str, JsonValue]:
    mapping: dict[str, JsonValue] = dict(rows)
    return mapping


def _milliseconds(nanoseconds: int) -> Decimal:
    return (Decimal(nanoseconds) / NANOSECONDS_PER_MILLISECOND).quantize(
        Decimal("0.000001")
    )
