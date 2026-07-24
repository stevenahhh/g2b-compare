"""Deterministic full and incremental source-window planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Final, Literal

from g2b_compare.contracts.quota import Operation

type SyncMode = Literal["full", "delta"]

BACKFILL_START: Final = date(2000, 1, 1)
DEFAULT_WINDOW_DAYS: Final = 31
OVERLAP_DAYS: Final = 2
KST: Final = timezone(timedelta(hours=9))
SOURCE_OPERATIONS: Final = tuple(Operation)[:5]
INVALID_WINDOW: Final = "invalid-window"
INVALID_WINDOW_SIZE: Final = "invalid-window-size"
NAIVE_OBSERVED_AT: Final = "naive-observed-at"
UNSPLITTABLE_WINDOW: Final = "unsplittable-window"
UNSUPPORTED_SOURCE_OPERATION: Final = "unsupported-source-operation"


@dataclass(frozen=True, slots=True)
class DateWindow:
    """One inclusive provider date window in persisted execution order."""

    ordinal: int
    start: date
    end: date

    def __post_init__(self) -> None:
        """Reject reversed windows and negative persisted ordinals."""
        if self.ordinal < 0 or self.start > self.end:
            raise SyncPlanningError(INVALID_WINDOW)


@dataclass(frozen=True, slots=True)
class OperationSchedule:
    """Ordered windows for one source operation and synchronization mode."""

    operation: Operation
    mode: SyncMode
    windows: tuple[DateWindow, ...]


class SyncPlanningError(ValueError):
    """A date or window cannot form a deterministic synchronization plan."""


def plan_full_sync(
    today: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[OperationSchedule, ...]:
    """Plan all five source operations through yesterday, including registration."""
    end = today - timedelta(days=1)
    windows = _partition(BACKFILL_START, end, window_days)
    return tuple(
        OperationSchedule(operation, "full", windows) for operation in SOURCE_OPERATIONS
    )


def plan_incremental_sync(
    operation: Operation,
    cursor: date,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> OperationSchedule:
    """Plan a two-day overlapping successor through KST yesterday."""
    if operation not in SOURCE_OPERATIONS:
        raise SyncPlanningError(UNSUPPORTED_SOURCE_OPERATION)
    if now.tzinfo is None or now.utcoffset() is None:
        raise SyncPlanningError(NAIVE_OBSERVED_AT)
    end = now.astimezone(KST).date() - timedelta(days=1)
    start = max(BACKFILL_START, cursor - timedelta(days=OVERLAP_DAYS))
    return OperationSchedule(operation, "delta", _partition(start, end, window_days))


def split_window(window: DateWindow) -> tuple[DateWindow, DateWindow]:
    """Bisect an inclusive window and return left before right."""
    if window.start == window.end:
        raise SyncPlanningError(UNSPLITTABLE_WINDOW)
    midpoint = window.start + (window.end - window.start) // 2
    return (
        DateWindow(window.ordinal, window.start, midpoint),
        DateWindow(window.ordinal + 1, midpoint + timedelta(days=1), window.end),
    )


def _partition(start: date, end: date, window_days: int) -> tuple[DateWindow, ...]:
    """Partition [start, end] chronologically, then order newest-first."""
    if window_days < 1:
        raise SyncPlanningError(INVALID_WINDOW_SIZE)
    if start > end:
        return ()
    bounds: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=window_days - 1))
        bounds.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(
        DateWindow(ordinal, window_start, window_end)
        for ordinal, (window_start, window_end) in enumerate(reversed(bounds))
    )
