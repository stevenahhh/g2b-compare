from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, final

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.materialization import MaterializationRepository
from g2b_compare.db.sql import as_int, query
from g2b_compare.sync.catalog import advance_catalog
from g2b_compare.sync.paginator import PageMeta
from g2b_compare.sync.planner import DateWindow, OperationSchedule
from g2b_compare.sync.publisher import (
    PublicationRequest,
    SourceDelta,
    publish_operation,
)
from g2b_compare.sync.runner import AttemptPage, CheckpointStore, OperationRunner
from tests.sync.todo8_fixture import (
    NOW,
    FixtureDatabase,
    add_page,
    complete_products,
    database,
    record,
    setup_five_sources,
)

if TYPE_CHECKING:
    from pathlib import Path

REVIEW_KILL = "review-kill"


@dataclass(frozen=True, slots=True)
class ReviewKillError(Exception):
    reason: str


@final
class Gate:
    def reserve(self, operation: Operation) -> int:
        _ = operation
        return 1

    def finish(
        self,
        reservation_id: int,
        status_code: int,
        operation: Operation,
        window: int,
        page: int,
    ) -> None:
        _ = (reservation_id, status_code, operation, window, page)


@dataclass(frozen=True, slots=True)
class TwoPageSource:
    crash_on_page_two: bool

    def fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> AttemptPage:
        _ = (operation, window)
        if self.crash_on_page_two and page_no == 2:
            raise ReviewKillError(REVIEW_KILL)
        return AttemptPage(
            status_code=200,
            metadata=PageMeta(page_no, 10, 15, 10 if page_no == 1 else 5),
            retryable=False,
        )


def independent_states(root: Path, mutate_resumed: bool) -> tuple[bytes, bytes]:
    uninterrupted = _execute(root / "uninterrupted.sqlite3", killed=False)
    resumed = _execute(root / "resumed.sqlite3", killed=True)
    if mutate_resumed:
        with connect(resumed.path) as connection:
            _ = query(
                connection,
                "UPDATE source_records SET canonical_record_sha = ?",
                ("mutation" * 8,),
            )
    return _frozen_source_state(uninterrupted), _frozen_source_state(resumed)


def seed_ready_release(path: Path) -> FixtureDatabase:
    db = database(path)
    setup_five_sources(db)
    advance = advance_catalog(path, NOW)
    attribute_id = complete_products(db, advance, ("P-1",))
    seed_ready_release_on(db, advance.catalog_generation_id, attribute_id)
    return db


def seed_ready_release_on(
    db: FixtureDatabase,
    catalog_id: int,
    attribute_id: int,
) -> None:
    materialization_id = MaterializationRepository(db.path).create(
        catalog_id,
        attribute_id,
        ("n-review", "p-review"),
    )
    with connect(db.path) as connection:
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = 'complete' WHERE id = ?",
            (materialization_id,),
        )
        index_id = _insert_id(
            query(
                connection,
                """INSERT INTO index_versions
                   VALUES(NULL, ?, 'idx-art', 'idx-man', 'complete', ?)""",
                (materialization_id, NOW),
            ).lastrowid
        )
        relation_id = _insert_id(
            query(
                connection,
                """INSERT INTO relation_snapshots
                   VALUES(NULL, 'source-man', 'relation-content', 'complete', ?)""",
                (NOW,),
            ).lastrowid
        )
        bundle_id = _insert_id(
            query(
                connection,
                """INSERT INTO release_bundles VALUES(
                    NULL, ?, ?, ?, 'rank-v1', 1, 1, 'cache-content', 'bundle-sha',
                    'ready', 1, 1, ?, ?)""",
                (materialization_id, index_id, relation_id, NOW, NOW),
            ).lastrowid
        )
        _ = query(
            connection,
            "INSERT INTO comparator_cache VALUES(?, 1, 'P-1', 1, '{}', 'payload-sha')",
            (bundle_id,),
        )
        _ = query(connection, "INSERT INTO active_release VALUES(1, ?)", (bundle_id,))


def _execute(path: Path, killed: bool) -> FixtureDatabase:
    db = database(path)
    setup_five_sources(db)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    schedule = OperationSchedule(
        operation,
        "delta",
        (DateWindow(0, date(2026, 7, 15), date(2026, 7, 15)),),
    )
    store = CheckpointStore(path, db.ingest)
    if killed:
        with suppress(ReviewKillError):
            _ = OperationRunner(
                store,
                Gate(),
                TwoPageSource(crash_on_page_two=True),
            ).run(schedule, NOW)
        run_id = _latest_run_id(path)
        result = OperationRunner(
            store,
            Gate(),
            TwoPageSource(crash_on_page_two=False),
        ).run(
            schedule,
            NOW,
            store.load(run_id),
        )
    else:
        result = OperationRunner(
            store,
            Gate(),
            TwoPageSource(crash_on_page_two=False),
        ).run(schedule, NOW)
    origin_page = add_page(db, operation.value, "publication")
    _ = publish_operation(
        path,
        PublicationRequest(
            operation,
            "delta",
            "2026-07-15",
            "2026-07-15",
            NOW,
            (SourceDelta(record("K-1", "P-1", origin_page, "a")),),
            result.validated_pages,
        ),
    )
    return db


def _frozen_source_state(db: FixtureDatabase) -> bytes:
    with connect(db.path) as connection:
        pointer = query(
            connection,
            """SELECT operation, snapshot_id
               FROM active_source_snapshots ORDER BY operation""",
        ).fetchall()
        snapshots = query(
            connection,
            """SELECT id, operation, parent_id, mode, window_start, window_end,
                      completeness, status FROM source_snapshots ORDER BY id""",
        ).fetchall()
        records = query(
            connection,
            """SELECT source_snapshot_id, operation, source_record_key, product_id,
                      canonical_record_sha, payload_sha, is_tombstone
               FROM source_records
               ORDER BY source_snapshot_id, operation, source_record_key""",
        ).fetchall()
    return json.dumps(
        {"pointers": pointer, "records": records, "snapshots": snapshots},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _latest_run_id(path: Path) -> int:
    with connect(path) as connection:
        row = query(connection, "SELECT MAX(id) FROM sync_runs").fetchone()
    assert row is not None
    return as_int(row[0])


def _insert_id(value: int | None) -> int:
    assert value is not None
    return value
