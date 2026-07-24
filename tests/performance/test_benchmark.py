"""Deterministic benchmark statistics and threshold contracts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from g2b_compare.evaluation.benchmark import (
    BenchmarkPlan,
    BenchmarkThresholdError,
    benchmark_operation,
    nearest_rank_percentile,
)

if TYPE_CHECKING:
    from collections.abc import Generator


def test_nearest_rank_percentile_is_not_interpolated() -> None:
    assert nearest_rank_percentile((1, 2, 3, 4, 100), Decimal("0.95")) == 100
    assert nearest_rank_percentile((1, 2, 3, 4), Decimal("0.50")) == 2


def test_benchmark_records_warmups_repetitions_and_machine_stats() -> None:
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1

    result = benchmark_operation(
        BenchmarkPlan("cache-hit", 3, 5, timedelta(seconds=1)),
        operation,
    )

    assert calls == 8
    assert result.repetitions == 5
    assert result.warmups == 3
    assert result.percentile_method == "nearest-rank"
    assert result.p50_ms <= result.p95_ms <= result.max_ms


def test_deterministic_delay_fixture_fails_the_named_threshold() -> None:
    ticks = iter((0, 400_000_000))

    def clock() -> int:
        return next(ticks)

    with pytest.raises(BenchmarkThresholdError, match="slow-search"):
        _ = benchmark_operation(
            BenchmarkPlan(
                "slow-search",
                0,
                1,
                timedelta(milliseconds=300),
            ),
            lambda: None,
            clock_ns=clock,
        )


def test_threshold_error_preserves_original_exception_through_contextmanager() -> None:
    @contextmanager
    def boundary() -> Generator[None]:
        yield

    benchmark = "slow-search"
    with (
        pytest.raises(BenchmarkThresholdError, match=benchmark),
        boundary(),
    ):
        raise BenchmarkThresholdError(
            benchmark,
            Decimal(301),
            Decimal(300),
        )
