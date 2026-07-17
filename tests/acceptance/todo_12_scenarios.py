from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.services.release import (
    ReleaseCoordinator,
    ReleaseDisposition,
    pin_active_release,
)
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchRequest
from g2b_compare.services.search_response import encode_search_response
from g2b_compare.services.sqlite_search import (
    SqliteComparatorCacheBuilder,
    SqliteSearchReader,
)
from tests.services.release_support import MutableClock
from tests.services.sqlite_search_support import search_database

from .todo_12_e0_scenarios import observe_e0
from .todo_12_release_scenarios import observe_release
from .todo_12_search_scenarios import observe_search

if TYPE_CHECKING:
    from pathlib import Path


SCENARIOS = (
    "empty-db",
    "no-result",
    "ambiguous-category",
    "upper-only-ambiguous",
    "detail-without-upper",
    "unknown-category",
    "unknown-detail-category",
    "detail-parent-mismatch",
    "price-requires-target",
    "tolerance-requires-target",
    "price-unit-required",
    "unknown-price-unit",
    "invalid-price-constraint",
    "empty-pool-with-supplied-unit",
    "empty-pool-before-unit-resolution",
    "invalid-price-before-unknown-category",
    "price-crossfield-before-category",
    "stale-snapshot",
    "query-too-long",
    "page-overflow",
    "candidate-0-2",
    "corrupt-cache",
    "release-kill-before-swap",
    "release-orphan-0959",
    "release-orphan-1000",
    "release-retry-same-tuple",
    "release-cache-short",
    "release-index-sha-drift",
    "release-relation-sha-drift",
    "relation-import-does-not-mutate-active",
    "request-bundle-pin",
    "e0-mixed-product-names",
    "e0-exact-name-candidate-nine",
    "e0-lane-inactive",
    "e0-lane-dedupe",
    "e0-lane-backfill",
    "e0-bundle-version-drift",
    "parser-source-order",
    "parser-stratum-overlap",
    "parser-text-dedup",
    "parser-stratum-forty-nine",
    "parser-template-sha",
    "stale-attempt-row-counted",
    "stale-attempt-row-served",
    "cache-payload-key-order",
    "cache-payload-decimal-equivalence",
    "cache-payload-array-order",
    "cache-content-sha-drift",
    "relation-content-sha-drift",
    "relation-source-manifest-sha-drift",
    "release-bundle-component-drift",
    "ready-same-tuple-noop",
    "ready-active-retry-rejected",
    "active-pointer-immutable-on-retry",
)

SEARCH_SCENARIOS = frozenset(SCENARIOS[:22])
E0_SCENARIOS = frozenset(SCENARIOS[31:42])


@dataclass(frozen=True, slots=True)
class HappyResult:
    active_ready: bool
    exact_cache_rows: int
    cached_uncached_equal: bool
    canonical_json_equal: bool
    category_auto_selected: bool
    price_flags: tuple[bool | None, ...]
    provenance_complete: bool
    request_pin_stable: bool
    search_read_only: bool


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


def run_happy(tmp_path: Path) -> HappyResult:
    fixture = search_database(tmp_path / "todo12-happy.sqlite3")
    release = fixture.release
    result = ReleaseCoordinator(release.path, MutableClock()).coordinate(
        release.candidate,
        SqliteComparatorCacheBuilder(release.path, release.candidate),
    )
    request = SearchRequest(
        product_name="영상감시장치",
        spec_text="800만화소",
        target_price_won=1_000_000,
    )
    with connect(release.path) as connection:
        before_row = query(connection, "PRAGMA data_version").fetchone()
        assert before_row is not None
        cached = execute_search(request, SqliteSearchReader(release.path))
        uncached = execute_search(
            request,
            SqliteSearchReader(release.path, cache_enabled=False),
        )
        after_row = query(connection, "PRAGMA data_version").fetchone()
        row = query(connection, "SELECT COUNT(*) FROM comparator_cache").fetchone()
    assert after_row is not None
    assert row is not None
    cache_rows = as_int(row[0])
    active_pin = pin_active_release(release.path)
    return HappyResult(
        active_ready=result.disposition is ReleaseDisposition.READY,
        exact_cache_rows=cache_rows,
        cached_uncached_equal=cached == uncached,
        canonical_json_equal=(
            encode_search_response(cached) == encode_search_response(uncached)
        ),
        category_auto_selected=(
            cached.selected_category is not None
            and cached.selected_category.detail_code == "4601"
        ),
        price_flags=tuple(item.within_price_tolerance for item in cached.results),
        provenance_complete=all(
            item.product.observed_option_roles and item.product.curated_relations
            for item in cached.results
        ),
        request_pin_stable=cached.release == uncached.release == active_pin,
        search_read_only=as_int(before_row[0]) == as_int(after_row[0]),
    )


def observe_failure(scenario: str, tmp_path: Path) -> FailureObservation:
    scenario_root = tmp_path / scenario
    scenario_root.mkdir()
    if scenario in SEARCH_SCENARIOS:
        observed = observe_search(scenario, str(tmp_path / f"{scenario}.sqlite3"))
    elif scenario in E0_SCENARIOS:
        observed = observe_e0(scenario, scenario_root)
    else:
        observed = observe_release(scenario, scenario_root)
    return FailureObservation(*observed)
