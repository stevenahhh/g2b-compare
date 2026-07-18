from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from itertools import product as cartesian_product
from typing import TYPE_CHECKING, TypedDict

import httpx
import pytest
from pydantic import TypeAdapter

from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import query
from g2b_compare.services.release import ReleaseCoordinator
from g2b_compare.services.search_models import CategoryRef
from g2b_compare.services.sqlite_search import SqliteComparatorCacheBuilder
from g2b_compare.web.app import create_app
from g2b_compare.web.sqlite_reader import WebSqliteSearchReader
from tests.services.release_support import MutableClock
from tests.services.sqlite_search_support import search_database
from tests.web.todo13_support import (
    FATAL_RELEASE,
    NO_READY_RELEASE,
    FixtureReader,
    get,
    product,
    reader,
    state,
    status_tokens,
)

pytestmark = pytest.mark.asyncio

if TYPE_CHECKING:
    from pathlib import Path


class _EnhancedPayload(TypedDict):
    choices: list[str]
    html: str
    kind: str
    primary_state: str


_PAYLOAD = TypeAdapter(_EnhancedPayload)
_KST = timezone(timedelta(hours=9))
_FRESHNESS_NOW = datetime(2026, 7, 18, 3, 0, tzinfo=UTC)


async def test_route_renders_verified_manifest_link_and_rejects_transient(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "todo2.json"
    _ = manifest.write_text(
        json.dumps(
            {
                "product_links": {
                    "P000": {
                        "stable_contract_item_management_number": "SAFE_001",
                        "share_link_preflight": {
                            "final_host": "shop.g2b.go.kr",
                            "no_redirect": True,
                            "status": 200,
                        },
                    },
                    "P001": {
                        "key": "TRANSIENT",
                        "stable_contract_item_management_number": "SAFE_002",
                        "share_link_preflight": {
                            "final_host": "shop.g2b.go.kr",
                            "no_redirect": True,
                            "status": 200,
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    response = await get(reader(2), link_manifest=manifest)

    assert (
        'href="https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo=SAFE_001"'
    ) in response.text
    assert 'data-copy-id="P001"' in response.text
    assert "TRANSIENT" not in response.text


async def test_enhanced_ambiguous_category_returns_typed_fragment() -> None:
    fixture = FixtureReader(
        (product(1), product(2, category=("20", "2001"))),
        (CategoryRef("10", "1001"), CategoryRef("20", "2001")),
    )

    response = await get(fixture, enhanced=True)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    payload = _PAYLOAD.validate_json(response.content)
    assert payload["primary_state"] == "validation-error"
    assert payload["kind"] == "category-choice"
    assert payload["choices"] == ["10/1001", "20/2001"]
    assert 'data-category-choice="10/1001"' in payload["html"]
    assert "검색 조건을 확인하세요" in payload["html"]


async def test_unsubmitted_request_inspects_release_before_initial() -> None:
    fatal = await get(reader(0, pin_error=FATAL_RELEASE), "/")
    inactive = await get(reader(0, pin_error=NO_READY_RELEASE), "/")
    active = await get(reader(0), "/")

    assert (fatal.status_code, state(fatal)) == (500, "fatal-error")
    assert (inactive.status_code, state(inactive)) == (503, "no-active-snapshot")
    assert state(active) == "initial"


async def test_result_pagination_preserves_all_search_parameters() -> None:
    path = (
        "/?product_name=CCTV&category_code=10&detail_category_code=1001"
        "&target_price_won=100001&price_unit=%EA%B0%9C"
        "&price_tolerance_pct=12.5&page=1"
    )
    response = await get(reader(51), path)

    match = re.search(r'<a class="next-page" href="([^"]+)">', response.text)

    assert match is not None
    href = match.group(1).replace("&amp;", "&")
    assert "product_name=CCTV" in href
    assert "category_code=10" in href
    assert "detail_category_code=1001" in href
    assert "target_price_won=100001" in href
    assert "price_unit=%EA%B0%9C" in href
    assert "price_tolerance_pct=12.5" in href
    assert "page=2" in href
    clicked = await get(reader(51), href)
    assert clicked.text.count("<tr data-statuses=") == 1


async def test_fatal_response_has_generated_request_id_only_on_500() -> None:
    fatal = await get(reader(0, pin_error=FATAL_RELEASE), "/")
    healthy = await get(reader(0), "/")

    assert re.search(r'data-request-id="[0-9a-f]{32}"', fatal.text)
    assert "요청 ID" in fatal.text
    assert "data-request-id=" not in healthy.text


async def test_partial_attribute_has_exact_visible_badge() -> None:
    response = await get(FixtureReader((product(1, coverage="1/3"),)))

    assert (
        '<span class="badge partial-attribute">개별 속성 일부 미수집</span>'
        in response.text
    )


async def test_create_app_default_and_injected_manifest_reach_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "todo2.json"
    _ = manifest.write_text('{"product_links":{}}', encoding="utf-8")
    for app in (
        create_app(reader(0)),
        create_app(reader(0), link_manifest=manifest),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://startup.test",
        ) as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert state(response) == "initial"


async def test_missing_and_empty_default_database_are_no_active(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.sqlite3"
    empty = tmp_path / "empty.sqlite3"
    migrate(empty)
    for database in (missing, empty):
        transport = httpx.ASGITransport(app=create_app(database=database))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://startup.test",
        ) as client:
            response = await client.get("/")
        assert response.status_code == 503
        assert state(response) == "no-active-snapshot"
        assert "검색 데이터가 아직 준비되지 않았습니다" in response.text


async def test_real_stale_failed_database_serves_last_good_rows(
    tmp_path: Path,
) -> None:
    fixture = search_database(tmp_path / "stale-failed.sqlite3")
    with connect(fixture.release.path) as connection:
        _ = query(
            connection,
            """
            UPDATE products
            SET data_as_of='2026-06-01T00:00:00+00:00'
            WHERE materialization_id=10
            """,
        )
        _ = query(
            connection,
            """
            INSERT INTO sync_runs(
                id,operation,mode,status,cursor_json,page_size,calls,
                started_at,finished_at,error_kind
            ) VALUES(
                999,'catalog','full','failed','{}',100,1,
                '2026-07-18T00:00:00+00:00',
                '2026-07-18T00:01:00+00:00','provider'
            )
            """,
        )
    builder = SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )
    _ = ReleaseCoordinator(fixture.release.path, MutableClock()).coordinate(
        fixture.release.candidate,
        builder,
    )
    transport = httpx.ASGITransport(
        app=create_app(database=fixture.release.path)
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://stale.test",
    ) as client:
        response = await client.get("/?product_name=영상감시장치")

    assert response.status_code == 200
    assert state(response) == "sync-failed-last-good"
    assert status_tokens(response) == {
        "partial-attribute",
        "stale",
        "sync-failed-last-good",
    }
    assert response.text.count("<tr data-statuses=") == 4
    assert "최근 동기화에 실패하여 이전 데이터를 표시합니다" in response.text


@pytest.mark.parametrize(
    ("data_as_of", "successful_at"),
    [
        ("2026-07-15", _FRESHNESS_NOW - timedelta(hours=1)),
        ("2026-07-16", _FRESHNESS_NOW - timedelta(hours=36, seconds=1)),
    ],
)
async def test_production_freshness_rejects_expired_source_or_sync(
    tmp_path: Path,
    data_as_of: str,
    successful_at: datetime,
) -> None:
    reader = _production_reader(tmp_path, data_as_of, successful_at)

    assert reader.web_statuses(reader.pin_active_release()) == ("stale",)


async def test_production_freshness_accepts_exact_boundaries(tmp_path: Path) -> None:
    cutoff = (_FRESHNESS_NOW.astimezone(_KST).date() - timedelta(days=2)).isoformat()
    reader = _production_reader(
        tmp_path,
        cutoff,
        _FRESHNESS_NOW - timedelta(hours=36),
    )

    assert reader.web_statuses(reader.pin_active_release()) == ()


@pytest.mark.parametrize(
    ("data_as_of", "successful_at"),
    [
        ("not-a-date", _FRESHNESS_NOW - timedelta(hours=1)),
        ("2026-07-18", None),
        ("2026-07-18", "not-a-time"),
    ],
)
async def test_production_freshness_fails_closed(
    tmp_path: Path,
    data_as_of: str,
    successful_at: datetime | str | None,
) -> None:
    reader = _production_reader(tmp_path, data_as_of, successful_at)

    assert reader.web_statuses(reader.pin_active_release()) == ("stale",)


async def test_generated_primary_state_truth_table_and_forbidden_pairs() -> None:
    axes = cartesian_product(
        (False, True),
        ("active", "fatal", "no-active"),
        (False, True),
        (False, True),
        (False, True),
    )
    for submitted, database, stale, sync_failed, has_matches in axes:
        pin_error = {
            "active": None,
            "fatal": FATAL_RELEASE,
            "no-active": NO_READY_RELEASE,
        }[database]
        statuses = tuple(
            token
            for token, enabled in (
                ("stale", stale),
                ("sync-failed-last-good", sync_failed),
            )
            if enabled
        )
        fixture = reader(
            4 if has_matches else 0,
            pin_error=pin_error,
            statuses=statuses,
        )
        path = "/?product_name=CCTV" if submitted else "/"
        response = await get(fixture, path)
        primary = state(response)
        tokens = status_tokens(response)
        expected = _expected_primary(
            submitted,
            database,
            stale,
            sync_failed,
            has_matches,
        )
        assert primary == expected
        assert response.status_code == _expected_http(database)
        assert tokens == _expected_tokens(database, stale, sync_failed)
        assert _expected_primary_banner(expected) in response.text
        for label in _expected_predicate_banners(tokens):
            assert label in response.text
        _assert_forbidden_pairs(response, primary, tokens, submitted)


def _expected_primary(
    submitted: bool,
    database: str,
    stale: bool,
    sync_failed: bool,
    has_matches: bool,
) -> str:
    candidates = (
        (database == "fatal", "fatal-error"),
        (database == "no-active", "no-active-snapshot"),
        (not submitted, "initial"),
        (sync_failed, "sync-failed-last-good"),
        (stale, "stale"),
        (has_matches, "current-results"),
        (True, "no-matches"),
    )
    return next(value for selected, value in candidates if selected)


def _expected_http(database: str) -> int:
    return {"active": 200, "fatal": 500, "no-active": 503}[database]


def _expected_tokens(
    database: str,
    stale: bool,
    sync_failed: bool,
) -> set[str]:
    if database != "active":
        return set()
    return {
        token
        for token, enabled in (
            ("stale", stale),
            ("sync-failed-last-good", sync_failed),
        )
        if enabled
    }


def _production_reader(
    tmp_path: Path,
    data_as_of: str,
    successful_at: datetime | str | None,
) -> WebSqliteSearchReader:
    fixture = search_database(tmp_path / "freshness.sqlite3")
    builder = SqliteComparatorCacheBuilder(
        fixture.release.path,
        fixture.release.candidate,
    )
    _ = ReleaseCoordinator(
        fixture.release.path,
        MutableClock(_FRESHNESS_NOW),
    ).coordinate(fixture.release.candidate, builder)
    with connect(fixture.release.path) as connection:
        _ = query(
            connection,
            "UPDATE products SET data_as_of=? WHERE materialization_id=10",
            (data_as_of,),
        )
        if successful_at is not None:
            finished_at = (
                successful_at.isoformat()
                if isinstance(successful_at, datetime)
                else successful_at
            )
            _ = query(
                connection,
                """
                INSERT INTO sync_runs(
                    id,operation,mode,status,cursor_json,page_size,calls,
                    started_at,finished_at,error_kind
                ) VALUES(998,'catalog','full','complete','{}',100,1,?,?,NULL)
                """,
                (finished_at, finished_at),
            )
    return WebSqliteSearchReader(
        fixture.release.path,
        clock=lambda: _FRESHNESS_NOW,
    )


def _expected_primary_banner(primary: str) -> str:
    return {
        "current-results": "현재 로컬 데이터 기준 결과",
        "fatal-error": "검색을 처리할 수 없습니다",
        "initial": "검색 조건을 입력하세요",
        "no-active-snapshot": "검색 데이터가 아직 준비되지 않았습니다",
        "no-matches": "정확히 일치하는 물품이 없습니다",
        "stale": "데이터가 오래되었습니다",
        "sync-failed-last-good": "최근 동기화에 실패하여 이전 데이터를 표시합니다",
    }[primary]


def _expected_predicate_banners(tokens: set[str]) -> set[str]:
    labels = {
        "stale": "데이터가 오래되었습니다",
        "sync-failed-last-good": "최근 동기화에 실패하여 이전 데이터를 표시합니다",
    }
    return {labels[token] for token in tokens}


def _assert_forbidden_pairs(
    response: httpx.Response,
    primary: str,
    tokens: set[str],
    submitted: bool,
) -> None:
    assert "loading" not in tokens
    assert tokens.isdisjoint(
        {
            "current-results",
            "fatal-error",
            "initial",
            "no-active-snapshot",
            "no-matches",
            "validation-error",
        }
    )
    assert _status_order(response) == sorted(tokens, key=str.encode)
    rows = response.text.count("<tr data-statuses=")
    empty_states = {
        "fatal-error",
        "initial",
        "no-active-snapshot",
        "validation-error",
    }
    assert primary not in empty_states or rows == 0
    assert primary != "current-results" or (
        tokens.isdisjoint({"stale", "sync-failed-last-good"}) and rows > 0
    )
    assert primary != "initial" or not submitted
    assert 'data-primary-state="loading"' not in response.text


def _status_order(response: httpx.Response) -> list[str]:
    marker = 'data-statuses="'
    value = response.text.split(marker, 1)[1].split('"', 1)[0]
    return value.split()
