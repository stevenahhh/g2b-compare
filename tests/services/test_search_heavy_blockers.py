from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import query
from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import ComparisonSlot, RankableProduct, top_three
from g2b_compare.services import sqlite_search
from g2b_compare.services.comparator_models import ComparatorStatus
from g2b_compare.services.comparators import (
    ProductRecord,
    compare_product,
)
from g2b_compare.services.release import (
    ReleaseCoordinator,
    open_release_reader,
    pin_active_release,
)
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import (
    SearchRequest,
    SearchServiceError,
)
from g2b_compare.services.search_response import (
    encode_search_response,
    search_response_schema_bytes,
)
from g2b_compare.services.sqlite_search import SqliteSearchReader
from tests.services.release_support import MutableClock
from tests.services.sqlite_search_support import search_database

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.ranking.features import PreparedFeatureContext


class _ReleaseProbe(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    ready_attempt_no: int


class _ResponseProbe(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    schema_version: Literal["1"]
    release: _ReleaseProbe


class _SchemaProperty(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)


class _SchemaProbe(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    type: Literal["object"]
    properties: dict[str, _SchemaProperty]


STATUS_TRIPLE: TypeAdapter[
    tuple[ComparatorStatus, ComparatorStatus, ComparatorStatus]
] = TypeAdapter(tuple[ComparatorStatus, ComparatorStatus, ComparatorStatus])


def test_release_reader_opens_sqlite_uri_read_only_before_any_pragma(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a ready release and an observed sqlite connect boundary
    fixture = search_database(tmp_path / "readonly.sqlite3")
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        sqlite_search.SqliteComparatorCacheBuilder(
            fixture.release.path,
            fixture.release.candidate,
        ),
    )
    pin = pin_active_release(fixture.release.path)
    original = sqlite3.connect
    connections: list[tuple[str, bool]] = []
    statements: list[str] = []

    def observed_connect(
        database: str | Path,
        timeout: float = 5.0,
        isolation_level: None = None,
        *,
        uri: bool = False,
    ) -> sqlite3.Connection:
        connections.append((str(database), uri))
        connection = original(
            database,
            timeout=timeout,
            isolation_level=isolation_level,
            uri=uri,
        )
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observed_connect)

    # When: the release graph is opened through the actual reader
    with (
        open_release_reader(fixture.release.path, pin) as reader,
        pytest.raises(sqlite3.OperationalError, match=r"readonly|read-only"),
    ):
        _ = query(reader, "CREATE TABLE forbidden(id INTEGER)")

    # Then: mode=ro existed at open time and no journal mutation was attempted
    assert connections
    assert all(
        uri and name.startswith("file:") and "mode=ro" in name
        for name, uri in connections
    )
    assert all("JOURNAL_MODE" not in statement.upper() for statement in statements)


def test_cache_hit_decodes_persisted_views_without_ranking_recomputation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a ready real cache and an instrumented Ranking-v1 top-three seam
    fixture = search_database(tmp_path / "cache-hit.sqlite3")
    builder = sqlite_search.SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        builder,
    )
    calls: list[str] = []
    original = top_three

    def counted_top_three(
        anchor: RankableProduct,
        candidates: tuple[RankableProduct, ...],
        context: PreparedFeatureContext | None = None,
    ) -> tuple[ComparisonSlot, ComparisonSlot, ComparisonSlot]:
        calls.append(anchor.product_id)
        return original(anchor, candidates, context)

    monkeypatch.setattr(
        "g2b_compare.services.comparators.top_three",
        counted_top_three,
    )
    request = SearchRequest(product_name="영상감시장치", spec_text="800만화소")

    # When: cached and uncached paths execute independently
    cached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=True),
    )
    cache_calls = tuple(calls)
    calls.clear()
    uncached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=False),
    )

    # Then: cache uses persisted views while fallback genuinely builds them
    assert cache_calls == ()
    assert calls
    assert cached == uncached


def test_search_response_has_canonical_newline_free_bytes_and_typed_schema(
    tmp_path: Path,
) -> None:
    # Given: equal cached and uncached typed responses
    fixture = search_database(tmp_path / "response.sqlite3")
    builder = sqlite_search.SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        builder,
    )
    request = SearchRequest(product_name="영상감시장치", spec_text="800만화소")
    cached = execute_search(request, SqliteSearchReader(fixture.release.path))
    uncached = execute_search(
        request,
        SqliteSearchReader(fixture.release.path, cache_enabled=False),
    )

    # When: the public response and schema are serialized
    cached_bytes = encode_search_response(cached)
    uncached_bytes = encode_search_response(uncached)
    schema_bytes = search_response_schema_bytes()

    # Then: payload bytes are canonical, identical, typed, and newline-free
    assert cached_bytes == uncached_bytes
    assert b"\n" not in cached_bytes
    assert cached_bytes == encode_search_response(cached)
    document = _ResponseProbe.model_validate_json(cached_bytes)
    schema = _SchemaProbe.model_validate_json(schema_bytes)
    assert document.schema_version == "1"
    assert document.release.ready_attempt_no == 1
    assert schema.type == "object"
    assert "results" in schema.properties


def test_persisted_data_age_reaches_versioned_stale_policy_with_fixed_clock(
    tmp_path: Path,
) -> None:
    # Given: persisted data older than the explicit freshness-v1 threshold
    fixture = search_database(tmp_path / "stale.sqlite3")
    with connect(fixture.release.path) as connection:
        _ = query(
            connection,
            "UPDATE products SET data_as_of='2026-07-01' WHERE materialization_id=10",
        )
    assert sqlite_search.FRESHNESS_POLICY_VERSION == "freshness-v1"
    reader = SqliteSearchReader(
        fixture.release.path,
        cache_enabled=False,
        freshness=sqlite_search.FreshnessPolicy(
            clock=lambda: datetime(2026, 7, 17, tzinfo=UTC)
        ),
    )

    # When/Then: the production search path exposes stale_snapshot
    with pytest.raises(SearchServiceError, match="stale_snapshot"):
        _ = execute_search(SearchRequest(product_name="영상감시장치"), reader)


@pytest.mark.parametrize(
    ("candidate_count", "expected"),
    [
        (0, ("insufficient_candidates",) * 3),
        (1, ("ok", "insufficient_candidates", "insufficient_candidates")),
        (2, ("ok", "ok", "insufficient_candidates")),
    ],
)
def test_comparator_shortage_status_is_typed_and_exactly_three(
    candidate_count: int,
    expected: tuple[ComparatorStatus, ComparatorStatus, ComparatorStatus],
) -> None:
    # Given: one anchor and exactly zero, one, or two eligible products
    anchor = _record("A")
    candidates = tuple(_record(f"C{index}") for index in range(candidate_count))

    # When: the real product comparator executes
    views = compare_product(anchor, (anchor, *candidates))

    # Then: all three typed slots carry the exact shortage status matrix
    statuses = STATUS_TRIPLE.validate_python(tuple(item.status for item in views))
    assert statuses == expected


def _record(product_id: str) -> ProductRecord:
    return ProductRecord(
        rankable=RankableProduct(
            product_id=product_id,
            category_key=("45", "4512"),
            product_name_key="영상감시장치",
            option_text="800만화소 30fps",
            active=True,
            price=ComparisonPrice(
                active=True,
                amount_won=1_000_000,
                unit_key="대",
                offer_key=("op", product_id),
                reason=None,
            ),
        ),
        product_name_raw="영상감시장치",
        data_as_of="2026-07-16",
        attribute_coverage="1/1",
    )
