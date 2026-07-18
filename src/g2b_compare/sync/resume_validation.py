"""Reconstruct publication capability from persisted complete sync pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import SqlRow, as_int, as_text, query
from g2b_compare.sync.paginator import (
    PageMeta,
    PageScope,
    PageSequence,
    SyncInvariantError,
    ValidatedPageSet,
)

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.sync.planner import OperationSchedule

CHECKPOINT_MALFORMED = "checkpoint-malformed"


def validated_pages(
    database: Path,
    run_id: int,
    schedule: OperationSchedule,
) -> tuple[ValidatedPageSet, ...]:
    """Reissue publication capabilities from fully persisted run pages."""
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT windows.ordinal,windows.window_start,windows.window_end,
                      runs.page_size,pages.page_no,pages.item_count,
                      pages.total_count
               FROM sync_windows AS windows
               JOIN sync_runs AS runs ON runs.id=windows.run_id
               JOIN sync_pages AS pages ON pages.window_id=windows.id
               WHERE windows.run_id=?
               ORDER BY windows.ordinal,pages.page_no""",
            (run_id,),
        ).fetchall()
    grouped: dict[int, list[SqlRow]] = {}
    for row in rows:
        grouped.setdefault(as_int(row[0]), []).append(row)
    validated: list[ValidatedPageSet] = []
    for window in schedule.windows:
        scope = PageScope(
            schedule.operation.value,
            window.start.isoformat(),
            window.end.isoformat(),
        )
        sequence = PageSequence.empty(scope)
        for row in grouped.get(window.ordinal, []):
            if (as_text(row[1]), as_text(row[2])) != (
                scope.window_start,
                scope.window_end,
            ):
                raise SyncInvariantError(CHECKPOINT_MALFORMED)
            sequence = sequence.add(
                PageMeta(
                    as_int(row[4]),
                    as_int(row[3]),
                    as_int(row[6]),
                    as_int(row[5]),
                )
            )
        validated.append(sequence.finalize())
    return tuple(validated)
