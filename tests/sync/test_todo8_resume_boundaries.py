from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, final

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.models import SourceRecordInput
from g2b_compare.db.sql import as_int, query
from g2b_compare.sync.paginator import PageMeta, SyncInvariantError
from g2b_compare.sync.planner import DateWindow, OperationSchedule
from g2b_compare.sync.publisher import (
    PublicationRequest,
    SourceDelta,
    publish_operation,
)
from g2b_compare.sync.runner import (
    AttemptPage,
    CheckpointStore,
    OperationRunner,
)
from tests.sync.todo8_fixture import (
    NOW,
    add_page,
    database,
    publish,
    record,
    validated_pages,
)

if TYPE_CHECKING:
    from pathlib import Path

INTENTIONAL_KILL = "intentional-mid-window-kill"


@final
class _Gate:
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
class _TwoPageSource:
    crash_on_page_two: bool

    def fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> AttemptPage:
        _ = (operation, window)
        if page_no == 2 and self.crash_on_page_two:
            raise RuntimeError(INTENTIONAL_KILL)
        item_count = 10 if page_no == 1 else 5
        return AttemptPage(
            status_code=200,
            metadata=PageMeta(page_no, 10, 15, item_count),
            retryable=False,
        )


def test_mid_window_checkpoint_resumes_at_page_two(tmp_path: Path) -> None:
    db = database(tmp_path / "resume.sqlite3")
    schedule = OperationSchedule(
        Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        "delta",
        (DateWindow(0, date(2026, 7, 15), date(2026, 7, 15)),),
    )
    store = CheckpointStore(db.path, db.ingest)
    runner = OperationRunner(
        store,
        _Gate(),
        _TwoPageSource(crash_on_page_two=True),
    )

    with pytest.raises(RuntimeError, match="intentional-mid-window-kill"):
        _ = runner.run(schedule, NOW)
    run_id = _latest_run_id(db.path)
    checkpoint = store.load(run_id)
    resumed = OperationRunner(
        store,
        _Gate(),
        _TwoPageSource(crash_on_page_two=False),
    ).run(
        schedule,
        NOW,
        checkpoint,
    )

    assert resumed.pages == 1
    assert store.load(run_id).complete


def test_explicit_cancel_requires_prior_matching_source_key(tmp_path: Path) -> None:
    db = database(tmp_path / "cancel.sqlite3")
    operation = Operation.GET_SHOPPING_MALL_PRODUCT_INFO
    page_id = add_page(db, operation.value, "base")
    _ = publish(
        db,
        operation,
        "full",
        (SourceDelta(record("K-1", "P-1", page_id, "a")),),
    )
    unknown = SourceRecordInput("UNKNOWN", "P-1", page_id, "{}", "b" * 64, "b" * 64)

    with pytest.raises(SyncInvariantError, match="registration-key-mismatch"):
        _ = publish_operation(
            db.path,
            PublicationRequest(
                operation,
                "delta",
                "2026-07-15",
                "2026-07-15",
                NOW,
                (SourceDelta(unknown, explicit_cancel=True),),
                validated_pages(
                    operation,
                    "2026-07-15",
                    "2026-07-15",
                    1,
                ),
            ),
        )


def _latest_run_id(path: Path) -> int:
    with connect(path) as connection:
        row = query(connection, "SELECT MAX(id) FROM sync_runs").fetchone()
    assert row is not None
    assert row[0] is not None
    return as_int(row[0])
