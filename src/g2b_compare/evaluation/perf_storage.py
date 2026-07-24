"""SQLite publication for deterministic performance products."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from g2b_compare.db.sql import query

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

BATCH_SIZE: Final = 1_000
PERF_PRODUCT_COUNT: Final = 50_000
PERF_CACHE_ROW_COUNT: Final = 150_000
CACHE_CORRUPT: Final = "cache-corrupt"
CACHE_COUNT_MISMATCH: Final = "cache-count-mismatch"


@dataclass(frozen=True, slots=True)
class PerfStorageRow:
    """One typed product row for the benchmark lookup database."""

    product_id: str
    category_no: str
    detail_category_no: str
    product_name: str
    payload: str


@dataclass(frozen=True, slots=True)
class PerfCacheError(Exception):
    """Reject a prebuilt cache with incomplete anchors or slots."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def write_perf_database(path: Path, source: Sequence[PerfStorageRow]) -> None:
    """Create an indexed immutable input database in deterministic row order."""
    with closing(sqlite3.connect(path)) as connection:
        _ = connection.executescript(
            """PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE products(
                product_id TEXT PRIMARY KEY,
                category_no TEXT NOT NULL,
                detail_category_no TEXT NOT NULL,
                product_name TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX products_search
            ON products(product_name, category_no, detail_category_no);"""
        )
        rows = [
            (
                row.product_id,
                row.category_no,
                row.detail_category_no,
                row.product_name,
                row.payload,
            )
            for row in source
        ]
        for start in range(0, len(rows), BATCH_SIZE):
            _ = connection.executemany(
                "INSERT INTO products VALUES(?,?,?,?,?)",
                rows[start : start + BATCH_SIZE],
            )
        connection.commit()
        _ = connection.execute("VACUUM")


def sqlite3_version() -> str:
    """Return the runtime SQLite version recorded in the corpus manifest."""
    return sqlite3.sqlite_version


def write_perf_cache(path: Path, pool_sizes: tuple[int, ...]) -> None:
    """Publish exactly three deterministic candidate IDs for every anchor."""
    with closing(sqlite3.connect(path)) as connection:
        _ = connection.executescript(
            """PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE comparator_cache(
                anchor_id TEXT NOT NULL,
                slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
                candidate_id TEXT NOT NULL,
                PRIMARY KEY(anchor_id, slot)
            );
            CREATE INDEX comparator_candidate ON comparator_cache(candidate_id);"""
        )
        rows: list[tuple[str, int, str]] = []
        for pool_index in range(500):
            size = pool_sizes[pool_index % len(pool_sizes)]
            for ordinal in range(size):
                anchor = f"PERF-{pool_index:03d}-{ordinal:03d}"
                for slot in range(1, 4):
                    candidate_ordinal = (ordinal + slot) % size
                    rows.append(
                        (
                            anchor,
                            slot,
                            f"PERF-{pool_index:03d}-{candidate_ordinal:03d}",
                        )
                    )
                    if len(rows) == BATCH_SIZE:
                        _ = connection.executemany(
                            "INSERT INTO comparator_cache VALUES(?,?,?)",
                            rows,
                        )
                        rows.clear()
        if rows:
            _ = connection.executemany(
                "INSERT INTO comparator_cache VALUES(?,?,?)",
                rows,
            )
        connection.commit()
        _ = connection.execute("VACUUM")
    validate_perf_cache(path)


def validate_perf_cache(path: Path) -> None:
    """Fail closed unless all 50k anchors own exact ordered three slots."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            row = query(
                connection,
                """SELECT COUNT(*), COUNT(DISTINCT anchor_id),
                          MIN(slot), MAX(slot)
                   FROM comparator_cache""",
            ).fetchone()
    except sqlite3.Error:
        raise PerfCacheError(CACHE_CORRUPT) from None
    if row != (PERF_CACHE_ROW_COUNT, PERF_PRODUCT_COUNT, 1, 3):
        raise PerfCacheError(CACHE_COUNT_MISMATCH)
