"""Restartable window/page execution over injected source and quota adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from g2b_compare.db.connection import connect
from g2b_compare.db.models import SyncRunInput, SyncWindowInput
from g2b_compare.db.sql import as_text, query
from g2b_compare.sync.attempts import (
    AttemptGate,
    AttemptPage,
    PageSource,
    PageSourceError,
)
from g2b_compare.sync.paginator import (
    PageMeta,
    PageScope,
    PageSequence,
    SyncInvariantError,
    ValidatedPageSet,
)
from g2b_compare.sync.resume_validation import validated_pages

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.contracts.quota import Operation
    from g2b_compare.db.ingest import IngestRepository
    from g2b_compare.sync.planner import DateWindow, OperationSchedule

ATTEMPTS_EXHAUSTED = "attempts-exhausted"
CHECKPOINT_MALFORMED = "checkpoint-malformed"
CHECKPOINT_MISSING = "checkpoint-missing"
ONE_DAY_OVER_BUDGET = "one-day-over-budget"
PERMANENT_PAGE_SOURCE_FAILURE = "permanent-page-source-failure"

__all__ = ["AttemptPage", "PageSourceError"]


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """Persisted next window/page cursor for a running operation."""

    run_id: int
    window_ordinal: int
    next_page: int
    complete: bool
    page_size: int | None = None
    total_count: int | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """Completed run identity and exact consumed attempt count."""

    run_id: int
    attempts: int
    pages: int
    validated_pages: tuple[ValidatedPageSet, ...]


class _CursorDocument(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    complete: bool
    next_page: int
    window_ordinal: int
    page_size: int | None = None
    total_count: int | None = None


@dataclass(frozen=True, slots=True)
class CheckpointStore:
    """SQLite cursor persistence over the existing sync run/window tables."""

    database: Path
    ingest: IngestRepository

    def start(self, schedule: OperationSchedule, started_at: str) -> RunCheckpoint:
        """Create one run and persist its windows left-to-right."""
        run_id = self.ingest.create_run(
            SyncRunInput(schedule.operation.value, schedule.mode, started_at)
        )
        for window in schedule.windows:
            _ = self.ingest.create_window(
                SyncWindowInput(
                    run_id,
                    window.ordinal,
                    window.start.isoformat(),
                    window.end.isoformat(),
                )
            )
        checkpoint = RunCheckpoint(run_id, 0, 1, not schedule.windows)
        self.save(checkpoint)
        return checkpoint

    def save(self, checkpoint: RunCheckpoint) -> None:
        """Atomically persist the next cursor after one verified page."""
        encoded = json.dumps(
            {
                "complete": checkpoint.complete,
                "next_page": checkpoint.next_page,
                "page_size": checkpoint.page_size,
                "total_count": checkpoint.total_count,
                "window_ordinal": checkpoint.window_ordinal,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with connect(self.database) as connection:
            _ = query(
                connection,
                "UPDATE sync_runs SET cursor_json = ? WHERE id = ?",
                (encoded, checkpoint.run_id),
            )

    def load(self, run_id: int) -> RunCheckpoint:
        """Reload the exact cursor after process restart."""
        with connect(self.database) as connection:
            row = query(
                connection,
                "SELECT cursor_json, status FROM sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise SyncInvariantError(CHECKPOINT_MISSING)
        try:
            value = _CursorDocument.model_validate_json(as_text(row[0]))
        except ValueError:
            raise SyncInvariantError(CHECKPOINT_MALFORMED) from None
        return RunCheckpoint(
            run_id,
            value.window_ordinal,
            value.next_page,
            value.complete,
            value.page_size,
            value.total_count,
        )

    def finish(self, run_id: int, finished_at: str, attempts: int) -> None:
        """Mark one cursor complete without altering any source pointer."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """UPDATE sync_runs SET status = 'complete', finished_at = ?, calls = ?
                   WHERE id = ?""",
                (finished_at, attempts, run_id),
            )


@dataclass(frozen=True, slots=True)
class OperationRunner:
    """Execute continuous pages with persisted checkpoints and bounded retries."""

    checkpoints: CheckpointStore
    gate: AttemptGate
    source: PageSource
    max_attempts: int = 3

    def run(
        self,
        schedule: OperationSchedule,
        observed_at: str,
        checkpoint: RunCheckpoint | None = None,
    ) -> RunResult:
        """Resume at the next unverified page and finish only continuous windows."""
        current = checkpoint or self.checkpoints.start(schedule, observed_at)
        if current.complete:
            return RunResult(
                current.run_id,
                0,
                0,
                validated_pages(self.checkpoints.database, current.run_id, schedule),
            )
        attempts = 0
        page_count = 0
        validated: list[ValidatedPageSet] = []
        for window in schedule.windows[current.window_ordinal :]:
            is_resumed_window = window.ordinal == current.window_ordinal
            scope = PageScope(
                schedule.operation.value,
                window.start.isoformat(),
                window.end.isoformat(),
            )
            page_no = current.next_page if is_resumed_window else 1
            sequence = (
                self._sequence(current, scope)
                if is_resumed_window
                else PageSequence.empty(scope)
            )
            while not sequence.complete:
                page, used = self._fetch(schedule.operation, window, page_no)
                attempts += used
                sequence = sequence.add(page)
                page_count += 1
                page_no += 1
                next_window = window.ordinal + int(sequence.complete)
                self.checkpoints.save(
                    RunCheckpoint(
                        run_id=current.run_id,
                        window_ordinal=next_window,
                        next_page=1 if sequence.complete else page_no,
                        complete=False,
                        page_size=None if sequence.complete else page.num_of_rows,
                        total_count=None if sequence.complete else page.total_count,
                    )
                )
            validated.append(sequence.finalize())
        self.checkpoints.save(
            RunCheckpoint(
                run_id=current.run_id,
                window_ordinal=len(schedule.windows),
                next_page=1,
                complete=True,
            )
        )
        self.checkpoints.finish(current.run_id, observed_at, attempts)
        return RunResult(current.run_id, attempts, page_count, tuple(validated))

    @staticmethod
    def _sequence(checkpoint: RunCheckpoint, scope: PageScope) -> PageSequence:
        if checkpoint.next_page == 1:
            return PageSequence.empty(scope)
        if checkpoint.page_size is None or checkpoint.total_count is None:
            raise SyncInvariantError(CHECKPOINT_MALFORMED)
        return PageSequence.resume(
            checkpoint.next_page,
            checkpoint.page_size,
            checkpoint.total_count,
            scope,
        )

    def _fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> tuple[PageMeta, int]:
        for attempt in range(1, self.max_attempts + 1):
            reservation_id = self.gate.reserve(operation)
            try:
                response = self.source.fetch(operation, window, page_no)
            except PageSourceError as caught:
                self.gate.finish(
                    reservation_id,
                    caught.status_code,
                    operation,
                    window.ordinal,
                    page_no,
                )
                if not caught.retryable:
                    raise SyncInvariantError(PERMANENT_PAGE_SOURCE_FAILURE) from None
                continue
            self.gate.finish(
                reservation_id,
                response.status_code,
                operation,
                window.ordinal,
                page_no,
            )
            if response.metadata is not None:
                return response.metadata, attempt
            if not response.retryable:
                break
        raise SyncInvariantError(ATTEMPTS_EXHAUSTED)


def require_daily_budget(planned_attempts: int, remaining_attempts: int) -> None:
    """Reject a one-day plan before dispatch when it cannot fit conservatively."""
    if planned_attempts > remaining_attempts:
        raise SyncInvariantError(ONE_DAY_OVER_BUDGET)
