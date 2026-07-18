from __future__ import annotations

import io
import logging
import sqlite3
import threading
from datetime import date, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import cast, final

import httpx
import pytest
import respx
from fastapi import FastAPI

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.wire import official_url
from g2b_compare.db.migrate import migrate
from g2b_compare.observability import runtime_sync
from g2b_compare.observability.data_status import data_statuses
from g2b_compare.observability.health import Probe, health
from g2b_compare.observability.logging import operation_log
from g2b_compare.observability.runtime_attributes import run_attribute_sync
from g2b_compare.observability.runtime_sync import run_catalog_sync
from g2b_compare.observability.secrets import CANARY, scan_stream, verify_secrets
from g2b_compare.observability.server import handler, run_server
from g2b_compare.sync.planner import DateWindow, OperationSchedule
from g2b_compare.sync.publisher import publish_operation as real_publish_operation
from tests.acceptance.todo_12_release_support import ready_candidate
from tests.sources.test_thing_list import attribute_body
from tests.sync.todo8_fixture import database as sync_database
from tests.sync.todo8_fixture import setup_five_sources
from tests.sync.todo8_review_support import seed_ready_release

PREPUBLICATION_CRASH = "synthetic-prepublication-crash"


def test_operation_log_allows_only_safe_fields() -> None:
    output = io.StringIO()
    logger = logging.getLogger("test-operation-log")
    logger.handlers = [logging.StreamHandler(output)]
    logger.setLevel(logging.INFO)
    operation_log(
        logger,
        operation="sync",
        status="ok",
        context={"run": 2, "url": "forbidden"},
    )
    assert output.getvalue() == '{"operation":"sync","run":2,"status":"ok"}\n'


def test_stream_scan_finds_cross_chunk_canary() -> None:
    stream = io.BytesIO(b"x" * (64 * 1024 - 5) + CANARY)
    assert scan_stream(stream, (CANARY,)) == "secret"


def test_all_storage_scans_sqlite_wal_visible_values(tmp_path: Path) -> None:
    # Given: a committed secret value remains visible through a live WAL connection.
    database = tmp_path / "runtime.sqlite3"
    writer = sqlite3.connect(database)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    _ = writer.execute("CREATE TABLE evidence(value TEXT)")
    _ = writer.execute("INSERT INTO evidence VALUES (?)", (CANARY.decode(),))
    writer.commit()

    # When: all runtime storage is scanned.
    leaks = verify_secrets(
        Path.cwd(),
        runtime_root=tmp_path,
        all_storage=True,
    )

    # Then: the SQLite value is found while the WAL is still active.
    writer.close()
    assert any(leak.path == database for leak in leaks)


def test_missing_database_is_empty(tmp_path: Path) -> None:
    probe = health(tmp_path / "missing.sqlite3")
    assert not probe.ok
    assert probe.status == "empty"


def test_server_passes_runtime_contract_to_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a custom HOME contract and an isolated server lifecycle.
    contract = tmp_path / "docs" / "api-contract-observed.json"
    contract.parent.mkdir()
    _ = contract.write_text("{}", encoding="utf-8")
    observed: list[Path] = []

    class AppModule:
        def create_app(self, *, database: Path, link_manifest: Path) -> FastAPI:
            _ = database
            observed.append(link_manifest)
            return FastAPI()

    @final
    class Server:
        RequestHandlerClass: type[object] = object

        def __init__(self, _address: tuple[str, int], _handler: object) -> None:
            pass

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            pass

    def app_module(_name: str) -> AppModule:
        return AppModule()

    monkeypatch.setattr(
        "g2b_compare.observability.server.import_module",
        app_module,
    )
    monkeypatch.setattr(
        "g2b_compare.observability.server.ThreadingHTTPServer",
        Server,
    )

    # When: the runtime server builds the UI.
    status = run_server(
        tmp_path / "g2b.sqlite3",
        tmp_path / "search-index.bin",
        contract,
        "127.0.0.1",
        0,
    )

    # Then: UI links use the exact same verified runtime contract.
    assert status == 130
    assert observed == [contract]


def test_ready_endpoint_transitions_from_fresh_503_to_ready_200(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one bound HTTP listener with mutable runtime readiness.
    probes = [Probe(ok=False, status="empty", detail={"database": "missing"})]

    def current_probe(
        _database: Path,
        *,
        root: Path | None = None,
        index_path: Path,
        contract_path: Path | None = None,
    ) -> Probe:
        _ = (root, index_path, contract_path)
        return probes[0]

    monkeypatch.setattr(
        "g2b_compare.observability.server.readiness",
        current_probe,
    )
    database = tmp_path / "g2b.sqlite3"
    index = tmp_path / "search-index.bin"
    contract = tmp_path / "docs" / "api-contract-observed.json"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(FastAPI(), database, index, contract),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = cast("tuple[str, int]", server.server_address)
    url = f"http://{host}:{port}/readyz"

    try:
        # When: a fresh runtime becomes ready without replacing the listener.
        fresh = httpx.get(url)
        probes[0] = Probe(ok=True, status="ready", detail={"data_statuses": []})
        ready = httpx.get(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Then: the same endpoint transitions from fail-closed to ready.
    assert fresh.status_code == 503
    assert ready.status_code == 200


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("current", ()),
        ("building", ("pending",)),
        ("failed", ("failed",)),
        ("complete", ("stale",)),
        ("partial", ("stale", "partial")),
    ],
)
def test_data_statuses_ignore_old_rows_and_distinguish_new_candidates(
    tmp_path: Path,
    candidate: str,
    expected: tuple[str, ...],
) -> None:
    # Given: a ready release whose older fixture rows have numerically larger IDs.
    database = tmp_path / "ready.sqlite3"
    _fixture, _result = ready_candidate(database)
    if candidate in {"building", "failed", "complete"}:
        with sqlite3.connect(database) as connection:
            _ = connection.execute(
                """INSERT INTO relation_snapshots
                   VALUES(999,?,?,?,?)""",
                (
                    f"manifest-{candidate}",
                    f"content-{candidate}",
                    candidate,
                    "2099-01-01T00:00:00+00:00",
                ),
            )
    elif candidate == "partial":
        with sqlite3.connect(database) as connection:
            _ = connection.execute(
                """INSERT INTO attribute_snapshots
                   VALUES(999,10,10,1,2,'complete',?)""",
                ("2099-01-01T00:00:00+00:00",),
            )

    # When: readiness classifies work beyond the active release.
    actual = data_statuses(database)

    # Then: old rows are absent and each candidate predicate remains distinct.
    assert actual == expected


@pytest.mark.parametrize(
    ("mode", "status", "is_newer", "expected"),
    [
        ("full", "building", True, ("pending",)),
        ("full", "failed", True, ("failed",)),
        ("delta", "building", True, ("pending",)),
        ("full", "building", False, ()),
    ],
)
def test_data_statuses_detect_causally_newer_full_and_delta_sources(
    tmp_path: Path,
    mode: str,
    status: str,
    is_newer: bool,
    expected: tuple[str, ...],
) -> None:
    # Given: an active release and one full or delta source candidate.
    database = tmp_path / "ready.sqlite3"
    _ = seed_ready_release(database)
    with sqlite3.connect(database) as connection:
        active = cast(
            "tuple[int, str, str, str] | None",
            connection.execute(
                """SELECT snapshots.id,snapshots.operation,snapshots.window_start,
                          snapshots.window_end
                   FROM active_source_snapshots AS pointers
                   JOIN source_snapshots AS snapshots
                     ON snapshots.id=pointers.snapshot_id
                   ORDER BY snapshots.operation LIMIT 1"""
            ).fetchone(),
        )
        assert active is not None
        parent_id = active[0] if mode == "delta" else None
        window_end = "2099-01-01" if is_newer else "2000-01-01"
        _ = connection.execute(
            """INSERT INTO source_snapshots(
                   operation,parent_id,mode,window_start,window_end,
                   completeness,status,published_at
               ) VALUES(?,?,?,?,?,'complete',?,NULL)""",
            (active[1], parent_id, mode, active[2], window_end, status),
        )

    # When: readiness classifies candidates against the served source boundary.
    actual = data_statuses(database)

    # Then: newer full and child delta candidates appear, while old full rows do not.
    assert actual == expected


@respx.mock
def test_catalog_sync_uses_concrete_live_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one verified one-page source schedule and an HTTP-level provider fake.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def one_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        one_schedule,
    )
    route = respx.get(official_url(operation)).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "OK"},
                    "body": {
                        "items": {
                            "item": [
                                {
                                    "shopngCntrctNo": "C1",
                                    "shopngCntrctSno": "1",
                                    "prdctIdntNo": "P1",
                                }
                            ]
                        },
                        "numOfRows": 100,
                        "pageNo": 1,
                        "totalCount": 1,
                    },
                }
            },
        )
    )

    # When: the shipped runtime composition performs a full sync.
    results = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # Then: raw evidence, parsed source rows, and the active pointer all persisted.
    assert route.called
    assert results[0].pages == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_blobs").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM sync_pages").fetchone() == (1,)
        assert connection.execute(
            "SELECT product_id FROM source_records"
        ).fetchone() == ("P1",)
        assert connection.execute(
            """SELECT records.product_id
               FROM active_source_snapshots AS active
               JOIN source_records AS records
                 ON records.source_snapshot_id=active.snapshot_id
               WHERE active.operation=?""",
            (operation.value,),
        ).fetchone() == ("P1",)


@respx.mock
def test_catalog_sync_resumes_persisted_page_without_replaying_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: page one persisted before an interrupt in a two-page full run.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def resumed_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        resumed_schedule,
    )
    route = respx.get(official_url(operation))
    attempts = 0

    def provider(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise KeyboardInterrupt
        page_no = int(_request.url.params["pageNo"])
        return httpx.Response(
            200,
            json=_catalog_body(f"P{page_no}", page_no, 2),
        )

    route.side_effect = provider
    with pytest.raises(KeyboardInterrupt):
        _ = run_catalog_sync(
            database,
            Path("docs/api-contract-observed.json"),
            "synthetic-test-key",
            "full",
        )

    # When: the same command is started again.
    results = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # Then: page one is not replayed and both records publish under one run.
    assert attempts == 3
    assert results[0].pages == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM sync_pages").fetchone() == (2,)
        assert connection.execute(
            "SELECT product_id FROM source_records ORDER BY product_id"
        ).fetchall() == [("P1",), ("P2",)]


@respx.mock
def test_catalog_sync_finishes_failed_quota_attempt_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the first provider dispatch fails before a response and the retry succeeds.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def one_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        one_schedule,
    )
    logged: list[tuple[str, str]] = []

    def capture_log(
        _logger: logging.Logger,
        *,
        operation: str,
        status: str,
        context: dict[str, int] | None = None,
    ) -> None:
        _ = context
        logged.append((operation, status))

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_quota.operation_log",
        capture_log,
    )
    route = respx.get(official_url(operation))
    route.side_effect = [
        httpx.ConnectError("synthetic-connect-failure"),
        httpx.Response(200, json=_catalog_body("P1", 1, 1)),
    ]

    # When: the production sync runner applies its bounded retry policy.
    results = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # Then: both reservations finish, failure is logged, and publication succeeds.
    assert results[0].attempts == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT reservation_state FROM api_call_ledger ORDER BY id"
        ).fetchall() == [("failed",), ("succeeded",)]
    assert (operation.value, "failed-http-0") in logged


@respx.mock
def test_catalog_sync_publishes_completed_run_after_prepublication_crash_without_refetch(  # noqa: E501
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the page persists and its run completes before publication crashes.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def one_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        one_schedule,
    )
    route = respx.get(official_url(operation)).mock(
        return_value=httpx.Response(200, json=_catalog_body("P1", 1, 1))
    )

    def crash_before_publish(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError(PREPUBLICATION_CRASH)

    monkeypatch.setattr(runtime_sync, "publish_operation", crash_before_publish)
    with pytest.raises(RuntimeError, match="synthetic-prepublication-crash"):
        _ = run_catalog_sync(
            database,
            Path("docs/api-contract-observed.json"),
            "synthetic-test-key",
            "full",
        )

    # When: the same production command is restarted after restoring publication.
    monkeypatch.setattr(runtime_sync, "publish_operation", real_publish_operation)
    results = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # Then: persisted pages publish under the original run without refetch.
    assert route.call_count == 1
    assert results[0].pages == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sync_runs").fetchone() == (1,)
        assert connection.execute(
            "SELECT product_id FROM source_records"
        ).fetchone() == ("P1",)


@respx.mock
def test_transient_runtime_attempts_each_have_one_reservation_and_context_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two transient 500 responses precede one successful provider response.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def one_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    logged: list[tuple[str, str, dict[str, int | str]]] = []

    def capture_log(
        _logger: logging.Logger,
        *,
        operation: str,
        status: str,
        context: dict[str, int | str] | None = None,
    ) -> None:
        logged.append((operation, status, context or {}))

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        one_schedule,
    )
    monkeypatch.setattr(
        "g2b_compare.observability.runtime_quota.operation_log",
        capture_log,
    )
    route = respx.get(official_url(operation))
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json=_catalog_body("P1", 1, 1)),
    ]

    # When: the production runtime applies its bounded transient retry policy.
    result = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # Then: outbound calls, reservations, and real request-context logs are one-to-one.
    assert result[0].attempts == 3
    assert route.call_count == 3
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT reservation_state FROM api_call_ledger ORDER BY id"
        ).fetchall() == [("failed",), ("failed",), ("succeeded",)]
    assert (
        operation.value,
        "failed-http-500",
        {"run": 1, "window": 0, "page": 1},
    ) in logged


@respx.mock
def test_permanent_runtime_failure_is_reserved_logged_and_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the provider permanently rejects the first authorized request.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )

    def one_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (schedule,)

    logged: list[tuple[str, str, dict[str, int | str]]] = []

    def capture_log(
        _logger: logging.Logger,
        *,
        operation: str,
        status: str,
        context: dict[str, int | str] | None = None,
    ) -> None:
        logged.append((operation, status, context or {}))

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        one_schedule,
    )
    monkeypatch.setattr(
        "g2b_compare.observability.runtime_quota.operation_log",
        capture_log,
    )
    route = respx.get(official_url(operation)).mock(return_value=httpx.Response(401))

    # When: the production runtime sees a permanent authentication failure.
    with pytest.raises(ValueError, match="permanent-page-source-failure"):
        _ = run_catalog_sync(
            database,
            Path("docs/api-contract-observed.json"),
            "synthetic-test-key",
            "full",
        )

    # Then: the one outbound call has one failed reservation and complete context.
    assert route.call_count == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT reservation_state FROM api_call_ledger ORDER BY id"
        ).fetchall() == [("failed",)]
    assert (
        operation.value,
        "failed-http-401",
        {"run": 1, "window": 0, "page": 1},
    ) in logged


@respx.mock
def test_delta_publication_copies_forward_untouched_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a published full snapshot containing two products.
    database = tmp_path / "g2b.sqlite3"
    migrate(database)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    full = OperationSchedule(
        operation,
        "full",
        (DateWindow(0, date(2026, 7, 1), date(2026, 7, 1)),),
    )
    delta = OperationSchedule(
        operation,
        "delta",
        (DateWindow(0, date(2026, 7, 2), date(2026, 7, 2)),),
    )

    def full_schedule(_today: date) -> tuple[OperationSchedule, ...]:
        return (full,)

    def delta_schedule(
        _operation: Operation,
        _cursor: date,
        _now: datetime,
    ) -> OperationSchedule:
        return delta

    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_full_sync",
        full_schedule,
    )
    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.plan_incremental_sync",
        delta_schedule,
    )
    monkeypatch.setattr(
        "g2b_compare.observability.runtime_schedule.SOURCE_OPERATIONS",
        (operation,),
    )
    route = respx.get(official_url(operation))
    route.side_effect = [
        httpx.Response(200, json=_catalog_rows(("P1", "P2"))),
        httpx.Response(200, json=_catalog_rows(("P1",), marker="changed")),
    ]
    _ = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "full",
    )

    # When: a delta changes P1 without mentioning P2.
    _ = run_catalog_sync(
        database,
        Path("docs/api-contract-observed.json"),
        "synthetic-test-key",
        "delta",
    )

    # Then: the successor points active, links its parent, and carries P2 forward.
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT parent_id,mode FROM source_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone() == (1, "delta")
        assert connection.execute(
            """SELECT records.product_id,records.is_tombstone
               FROM active_source_snapshots AS active
               JOIN source_records AS records
                 ON records.source_snapshot_id=active.snapshot_id
               ORDER BY records.product_id"""
        ).fetchall() == [("P1", 0), ("P2", 0)]


@respx.mock
def test_attribute_sync_persists_complete_product_outcome(tmp_path: Path) -> None:
    # Given: five published sources queue one active product for enrichment.
    fixture = sync_database(tmp_path / "g2b.sqlite3")
    setup_five_sources(fixture)
    operation = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
    route = respx.get(official_url(operation)).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=attribute_body(product_id="P-1", page_size=100),
        )
    )

    # When: the shipped attribute runtime drains the persisted queue.
    applied = run_attribute_sync(
        fixture.path,
        Path("docs/api-contract-observed.json"),
        tmp_path / "raw",
        "synthetic-test-key",
    )

    # Then: evidence, record, state, and queue completion persist together.
    assert route.called
    assert applied == 1
    with sqlite3.connect(fixture.path) as connection:
        assert connection.execute(
            "SELECT product_id FROM attribute_records"
        ).fetchall() == [("P-1",)]
        assert connection.execute(
            "SELECT fetch_status FROM attribute_product_states"
        ).fetchall() == [("complete-nonempty",)]
        assert connection.execute(
            "SELECT COUNT(*) FROM attribute_enrichment_queue"
        ).fetchone() == (0,)


def _catalog_body(product_id: str, page_no: int, total: int) -> dict[str, object]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {
                "items": {
                    "item": [
                        {
                            "shopngCntrctNo": "C1",
                            "shopngCntrctSno": str(page_no),
                            "prdctIdntNo": product_id,
                        }
                    ]
                },
                "numOfRows": 1,
                "pageNo": page_no,
                "totalCount": total,
            },
        }
    }


def _catalog_rows(
    product_ids: tuple[str, ...],
    marker: str = "original",
) -> dict[str, object]:
    items = [
        {
            "shopngCntrctNo": "C1",
            "shopngCntrctSno": str(index),
            "prdctIdntNo": product_id,
            "marker": marker,
        }
        for index, product_id in enumerate(product_ids, start=1)
    ]
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {
                "items": {"item": items},
                "numOfRows": 100,
                "pageNo": 1,
                "totalCount": len(product_ids),
            },
        }
    }
