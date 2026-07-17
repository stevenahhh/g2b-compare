from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from pydantic import ConfigDict, TypeAdapter

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.ranking.cache import CacheJsonValue
from g2b_compare.services.release import ReleaseCoordinator
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import CategoryRef, SearchRequest
from g2b_compare.services.sqlite_search import (
    SqliteComparatorCacheBuilder,
    SqliteSearchReader,
)
from tests.services.release_support import MutableClock
from tests.services.sqlite_search_support import search_database

if TYPE_CHECKING:
    from pathlib import Path

DECIMAL_VALUE: Final[TypeAdapter[str | None]] = TypeAdapter(
    str | None,
    config=ConfigDict(strict=True),
)
DOCUMENT_VALUE: Final[TypeAdapter[dict[str, CacheJsonValue]]] = TypeAdapter(
    dict[str, CacheJsonValue],
    config=ConfigDict(strict=True),
)
SCORES_VALUE: Final[TypeAdapter[dict[str, str | None]]] = TypeAdapter(
    dict[str, str | None],
    config=ConfigDict(strict=True),
)
OPTION_ROLES_VALUE: Final[TypeAdapter[list[dict[str, CacheJsonValue]]]] = (
    TypeAdapter(
        list[dict[str, CacheJsonValue]],
        config=ConfigDict(strict=True),
    )
)
INTEGER_VALUE: Final[TypeAdapter[int]] = TypeAdapter(
    int,
    config=ConfigDict(strict=True),
)
SIX_DECIMALS: Final = re.compile(r"^-?\d+\.\d{6}$")


def test_real_reader_returns_identical_cached_and_uncached_responses(
    tmp_path: Path,
) -> None:
    # Given: one real four-product materialization and its precomputed cache
    fixture = search_database(tmp_path / "search.sqlite3")
    builder = SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        builder,
    )
    request = SearchRequest(
        product_name="영상감시장치",
        spec_text="800만화소",
        target_price_won=1_000_000,
    )

    # When: the same request uses cache and deterministic fallback paths
    cached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=True),
    )
    uncached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=False),
    )

    # Then: both paths expose the exact pinned graph and provenance
    assert cached == uncached
    assert cached.selected_category == CategoryRef("46", "4601")
    assert tuple(item.within_price_tolerance for item in cached.results) == (
        True,
        True,
        True,
        False,
    )
    assert all(item.product.observed_option_roles for item in cached.results)
    assert all(item.product.curated_relations for item in cached.results)
    with connect(fixture.release.path) as connection:
        row = query(connection, "SELECT COUNT(*) FROM comparator_cache").fetchone()
    assert row is not None
    assert as_int(row[0]) == 12


def test_real_builder_emits_the_exact_typed_cache_document(tmp_path: Path) -> None:
    # Given: a candidate with real attributes, prices, roles, and relations
    fixture = search_database(tmp_path / "payload.sqlite3")
    builder = SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )

    # When: comparator payloads are built for one anchor
    payloads = builder.slots_for("A")

    # Then: all three payloads have the release contract shape and fixed decimals
    assert len(payloads) == 3
    for slot, payload in enumerate(payloads, start=1):
        document = DOCUMENT_VALUE.validate_python(payload.root)
        assert set(document) == {
            "anchor_id",
            "candidate_id",
            "matched_quantities",
            "missing_reasons",
            "option_role_observations",
            "schema_version",
            "scores",
            "slot",
        }
        assert document["anchor_id"] == "A"
        assert document["slot"] == slot
        scores = SCORES_VALUE.validate_python(document["scores"])
        assert set(scores) == {"F", "L", "P", "S", "U", "coverage"}
        decimals = tuple(
            DECIMAL_VALUE.validate_python(value) for value in scores.values()
        )
        assert all(
            value is None or SIX_DECIMALS.fullmatch(value) for value in decimals
        )
        roles = OPTION_ROLES_VALUE.validate_python(
            document["option_role_observations"]
        )
        for role in roles:
            assert INTEGER_VALUE.validate_python(role["item_sequence"]) >= 0
            assert INTEGER_VALUE.validate_python(role["change_sequence"]) >= 0
