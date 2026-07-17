from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, final

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.services.release import (
    ComparatorCacheBuilder,
    ReleaseContractError,
    ReleaseCoordinator,
    ReleaseResult,
)
from tests.services.release_support import (
    MutableClock,
    PayloadBuilder,
    ReleaseFixture,
    SimulatedHardKillError,
    payload,
    release_database,
)

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.ranking.cache import CachePayload


@final
class MutationBuilder:
    __slots__ = ("_calls", "_database", "_statement")

    def __init__(self, database: Path, statement: str) -> None:
        self._database = database
        self._statement = statement
        self._calls = 0

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        self._calls += 1
        if self._calls == 1:
            with connect(self._database) as connection:
                _ = query(connection, self._statement)
        return tuple(payload(anchor_id, slot) for slot in range(1, 4))


def ready_candidate(path: Path) -> tuple[ReleaseFixture, ReleaseResult]:
    fixture = release_database(path)
    result = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
        fixture.candidate,
        PayloadBuilder(fixture.path),
    )
    return fixture, result


def killed_attempt(
    path: Path,
) -> tuple[ReleaseFixture, MutableClock, ReleaseCoordinator]:
    fixture = release_database(path)
    clock = MutableClock()
    coordinator = ReleaseCoordinator(fixture.path, clock)
    try:
        _ = coordinator.coordinate(
            fixture.candidate,
            PayloadBuilder(fixture.path, kill_after_calls=2),
        )
    except SimulatedHardKillError:
        return fixture, clock, coordinator
    raise AssertionError


def ready_after_retry(path: Path) -> tuple[ReleaseFixture, ReleaseResult]:
    fixture, clock, coordinator = killed_attempt(path)
    clock.advance(timedelta(minutes=10))
    return fixture, coordinator.coordinate(
        fixture.candidate,
        PayloadBuilder(fixture.path),
    )


def release_error(
    fixture: ReleaseFixture,
    builder: ComparatorCacheBuilder,
) -> tuple[str, str]:
    try:
        _ = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
            fixture.candidate,
            builder,
        )
    except ReleaseContractError as error:
        return type(error).__name__, str(error)
    raise AssertionError


def result_observation(result: ReleaseResult) -> tuple[str, str]:
    return (
        type(result).__name__,
        f"{result.disposition.value}; attempt={result.attempt_no}",
    )


def candidate_attempt(fixture: ReleaseFixture) -> int:
    with connect(fixture.path) as connection:
        row = query(
            connection,
            "SELECT attempt_no FROM release_bundles WHERE materialization_id=10",
        ).fetchone()
    assert row is not None
    return as_int(row[0])
