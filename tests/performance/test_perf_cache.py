"""Prebuilt 50k-anchor comparator cache integrity contracts."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.sql import as_int, query
from g2b_compare.evaluation.perf_population import POOL_SIZES
from g2b_compare.evaluation.perf_storage import (
    PerfCacheError,
    validate_perf_cache,
    write_perf_cache,
)

if TYPE_CHECKING:
    from pathlib import Path
    from sqlite3 import Connection


def test_prebuilt_cache_has_exact_150k_slots(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"

    write_perf_cache(path, POOL_SIZES)

    validate_perf_cache(path)
    with sqlite3.connect(path) as connection:
        assert _count(connection) == 150_000


def test_prebuilt_cache_rejects_count_drift_and_corrupt_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.sqlite3"
    write_perf_cache(path, POOL_SIZES)
    with sqlite3.connect(path) as connection:
        _ = connection.execute(
            "DELETE FROM comparator_cache WHERE anchor_id='PERF-000-000' AND slot=1"
        )
        connection.commit()

    with pytest.raises(PerfCacheError, match="cache-count-mismatch"):
        validate_perf_cache(path)

    corrupt = tmp_path / "corrupt.sqlite3"
    _ = corrupt.write_bytes(b"not-sqlite")
    with pytest.raises(PerfCacheError, match="cache-corrupt"):
        validate_perf_cache(corrupt)


def _count(connection: Connection) -> int:
    row = query(connection, "SELECT COUNT(*) FROM comparator_cache").fetchone()
    assert row is not None
    return as_int(row[0])
