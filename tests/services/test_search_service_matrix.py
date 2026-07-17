from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_text, query
from g2b_compare.services.release import ReleaseCoordinator
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchRequest
from g2b_compare.services.sqlite_search import (
    SqliteComparatorCacheBuilder,
    SqliteSearchReader,
)
from tests.services.release_support import MutableClock
from tests.services.sqlite_search_support import PRODUCT_IDS, search_database

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("pool_size", [1, 2, 3])
def test_execute_search_returns_exact_three_slots_for_short_pools(
    tmp_path: Path,
    pool_size: int,
) -> None:
    fixture = search_database(tmp_path / f"pool-{pool_size}.sqlite3")
    with connect(fixture.release.path) as connection:
        for product_id in PRODUCT_IDS[pool_size:]:
            _ = query(
                connection,
                """UPDATE products SET active=0
                   WHERE materialization_id=10 AND product_id=?""",
                (product_id,),
            )
        row = query(
            connection,
            """SELECT product_name_raw FROM products
               WHERE materialization_id=10 AND active=1 LIMIT 1""",
        ).fetchone()
    assert row is not None
    product_name = as_text(row[0])
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        SqliteComparatorCacheBuilder(
            fixture.release.path,
            fixture.release.candidate,
        ),
    )
    request = SearchRequest(product_name=product_name)

    cached = execute_search(request, SqliteSearchReader(fixture.release.path))
    uncached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=False),
    )

    assert cached == uncached
    assert len(cached.results) == pool_size
    for result in cached.results:
        slots = result.comparators
        populated = tuple(slot for slot in slots if slot.candidate is not None)
        empty = tuple(slot for slot in slots if slot.candidate is None)
        candidate_ids = tuple(
            slot.candidate.rankable.product_id
            for slot in slots
            if slot.candidate is not None
        )
        assert len(slots) == 3
        assert tuple(slot.rank for slot in slots) == (1, 2, 3)
        assert len(populated) == pool_size - 1
        assert len(empty) == 3 - len(populated)
        assert all(slot.status == "ok" for slot in populated)
        assert all(slot.status == "insufficient_candidates" for slot in empty)
        assert result.product.rankable.product_id not in candidate_ids
        assert len(candidate_ids) == len(frozenset(candidate_ids))
