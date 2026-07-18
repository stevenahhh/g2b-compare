from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Final, Literal, Never, assert_never, final

from pydantic import TypeAdapter

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.sync.attribute_queue import apply_fetch
from g2b_compare.sync.attribute_queue_state import FailedFetch, FetchCommit
from g2b_compare.sync.paginator import PageMeta, PageSequence
from g2b_compare.sync.planner import (
    DateWindow,
    OperationSchedule,
    plan_incremental_sync,
)
from g2b_compare.sync.runner import (
    AttemptPage,
    CheckpointStore,
    OperationRunner,
    require_daily_budget,
)
from tests.sync.todo8_failure_db_cases import observe_database_case
from tests.sync.todo8_fixture import NOW, database

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

type CoreScenario = Literal[
    "missing-window-page",
    "duplicate-window-page",
    "changing-total",
    "one-day-over-budget",
    "kst-boundary",
    "stale-attribute-target",
    "retry-charged",
]
CORE_SCENARIOS: Final = frozenset(
    {
        "missing-window-page",
        "duplicate-window-page",
        "changing-total",
        "one-day-over-budget",
        "kst-boundary",
        "stale-attribute-target",
        "retry-charged",
    }
)
BUDGET_NOT_REJECTED = "budget-not-rejected"
CORE_ADAPTER: Final[TypeAdapter[CoreScenario]] = TypeAdapter[CoreScenario](CoreScenario)


def observe_case(scenario: str, path: Path, now: datetime) -> str:
    if scenario in CORE_SCENARIOS:
        return _observe_core(CORE_ADAPTER.validate_python(scenario), path, now)
    return observe_database_case(scenario, path)


def _observe_core(scenario: CoreScenario, path: Path, now: datetime) -> str:
    match scenario:
        case "missing-window-page" | "duplicate-window-page" | "changing-total":
            return _pagination_failure(scenario)
        case "one-day-over-budget":
            return _budget_failure()
        case "kst-boundary":
            schedule = plan_incremental_sync(
                Operation.GET_SHOPPING_MALL_PRODUCT_INFO,
                date(2026, 7, 10),
                now,
            )
            return f"kst-end={schedule.windows[-1].end.isoformat()}"
        case "stale-attribute-target":
            result = apply_fetch(
                AttributeRepository(path),
                FetchCommit(1, 2, 0, "P-1", "f" * 64, FailedFetch("stale")),
            )
            return f"stale-attribute-{result}"
        case "retry-charged":
            return _retry_observation(path)
        case _:
            assert_never(scenario)


def _pagination_failure(scenario: str) -> Never:
    sequence = PageSequence.empty()
    if scenario == "missing-window-page":
        _ = sequence.add(PageMeta(2, 10, 20, 10))
    first = sequence.add(PageMeta(1, 10, 20, 10))
    if scenario == "duplicate-window-page":
        _ = first.add(PageMeta(1, 10, 20, 10))
    _ = first.add(PageMeta(2, 10, 21, 10))
    raise AssertionError(scenario)


def _budget_failure() -> Never:
    require_daily_budget(901, 900)
    raise AssertionError(BUDGET_NOT_REJECTED)


@final
class _Gate:
    reservations: int

    def __init__(self) -> None:
        self.reservations = 0

    def reserve(self, operation: Operation) -> int:
        _ = operation
        self.reservations += 1
        return self.reservations

    def finish(
        self,
        reservation_id: int,
        status_code: int,
        operation: Operation,
        window: int,
        page: int,
    ) -> None:
        _ = (reservation_id, status_code, operation, window, page)


@final
class _Source:
    calls: int

    def __init__(self) -> None:
        self.calls = 0

    def fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> AttemptPage:
        _ = (operation, window, page_no)
        self.calls += 1
        if self.calls == 1:
            return AttemptPage(status_code=503, metadata=None, retryable=True)
        return AttemptPage(
            status_code=200,
            metadata=PageMeta(1, 10, 1, 1),
            retryable=False,
        )


def _retry_observation(path: Path) -> str:
    db = database(path)
    schedule = OperationSchedule(
        Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        "delta",
        (DateWindow(0, date(2026, 7, 15), date(2026, 7, 15)),),
    )
    gate = _Gate()
    _ = OperationRunner(CheckpointStore(path, db.ingest), gate, _Source()).run(
        schedule,
        NOW,
    )
    return f"retry-reservations={gate.reservations}"
