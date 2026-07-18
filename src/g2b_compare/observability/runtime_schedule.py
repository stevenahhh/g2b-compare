"""Runtime source schedule and allowlisted request parameters."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Literal

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_text, query
from g2b_compare.sync.planner import (
    BACKFILL_START,
    SOURCE_OPERATIONS,
    DateWindow,
    OperationSchedule,
    plan_full_sync,
    plan_incremental_sync,
)

type SyncMode = Literal["full", "delta"]
PAGE_SIZE = 100

if TYPE_CHECKING:
    from pathlib import Path


def schedules(
    database: Path,
    mode: SyncMode,
    now: datetime,
) -> tuple[OperationSchedule, ...]:
    """Plan a full backfill or per-operation overlapping successor."""
    if mode == "full":
        return plan_full_sync(now.date())
    return tuple(
        plan_incremental_sync(operation, _cursor(database, operation), now)
        for operation in SOURCE_OPERATIONS
    )


def request_params(
    operation: Operation,
    window: DateWindow,
    page_no: int,
) -> tuple[tuple[str, str], ...]:
    """Build only provider-observed noncredential parameters."""
    base = (("type", "json"), ("pageNo", str(page_no)), ("numOfRows", str(PAGE_SIZE)))
    if operation in {
        Operation.GET_DELIVERY_REQUEST_DETAIL,
        Operation.GET_SHOPPING_MALL_PRODUCT_INFO,
    }:
        return (
            *base,
            ("inqryDiv", "1"),
            ("inqryBgnDate", window.start.strftime("%Y%m%d")),
            ("inqryEndDate", window.end.strftime("%Y%m%d")),
        )
    return (
        *base,
        ("rgstDtBgnDt", window.start.strftime("%Y%m%d0000")),
        ("rgstDtEndDt", window.end.strftime("%Y%m%d2359")),
    )


def _cursor(database: Path, operation: Operation) -> date:
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT snapshots.window_end
               FROM active_source_snapshots AS active
               JOIN source_snapshots AS snapshots ON snapshots.id=active.snapshot_id
               WHERE active.operation=?""",
            (operation.value,),
        ).fetchone()
    return BACKFILL_START if row is None else date.fromisoformat(as_text(row[0]))
