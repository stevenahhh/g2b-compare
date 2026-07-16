from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.sync.paginator import PageMeta, PageSequence, SyncInvariantError
from g2b_compare.sync.planner import (
    DateWindow,
    plan_full_sync,
    plan_incremental_sync,
    split_window,
)


def test_full_plan_is_exactly_five_sources_and_registration_backfills() -> None:
    schedules = plan_full_sync(date(2026, 7, 16))

    assert tuple(item.operation for item in schedules) == tuple(Operation)[:5]
    registration = schedules[3]
    assert registration.windows[0].start == date(2000, 1, 1)
    assert registration.windows[-1].end == date(2026, 7, 15)
    assert tuple(item.ordinal for item in registration.windows) == tuple(
        range(len(registration.windows))
    )


def test_incremental_plan_has_two_day_overlap_and_kst_day_boundary() -> None:
    schedule = plan_incremental_sync(
        Operation.GET_SHOPPING_MALL_PRODUCT_INFO,
        date(2026, 7, 10),
        datetime(2026, 7, 16, 0, 30, tzinfo=UTC),
    )

    assert schedule.windows[0].start == date(2026, 7, 8)
    assert schedule.windows[-1].end == date(2026, 7, 15)


def test_split_window_is_left_then_right_with_stable_ordinals() -> None:
    left, right = split_window(DateWindow(7, date(2026, 1, 1), date(2026, 1, 10)))

    assert (left.ordinal, right.ordinal) == (7, 8)
    assert left.end < right.start
    assert (left.start, right.end) == (date(2026, 1, 1), date(2026, 1, 10))


def test_pagination_completes_only_at_provider_formula() -> None:
    sequence = PageSequence.empty()
    sequence = sequence.add(PageMeta(1, 10, 25, 10))
    sequence = sequence.add(PageMeta(2, 10, 25, 10))
    sequence = sequence.add(PageMeta(3, 10, 25, 5))

    assert sequence.complete
    assert sequence.finalize().total_count == 25


@pytest.mark.parametrize(
    ("pages", "reason"),
    [
        (((2, 10, 20, 10),), "missing-window-page"),
        (((1, 10, 20, 10), (1, 10, 20, 10)), "duplicate-window-page"),
        (((1, 10, 20, 10), (2, 10, 21, 10)), "changing-total"),
    ],
)
def test_pagination_fails_closed(
    pages: tuple[tuple[int, int, int, int], ...],
    reason: str,
) -> None:
    sequence = PageSequence.empty()

    def add_pages() -> None:
        nonlocal sequence
        for page in pages:
            sequence = sequence.add(PageMeta(*page))

    with pytest.raises(SyncInvariantError, match=reason):
        add_pages()
