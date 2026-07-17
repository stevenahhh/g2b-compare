from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final

from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import query
from g2b_compare.ranking.cache import CachePayload
from g2b_compare.services.release import ReleaseCandidate

if TYPE_CHECKING:
    from pathlib import Path
    from sqlite3 import Connection

NOW = datetime(2026, 7, 17, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ReleaseFixture:
    path: Path
    candidate: ReleaseCandidate
    previous_bundle_id: int


@final
class MutableClock:
    """Advance deterministic coordinator time without wall-clock sleeps."""

    __slots__ = ("now",)

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@final
class PayloadBuilder:
    """Return typed cache payloads and optionally fail or mutate once."""

    __slots__ = (
        "calls",
        "kill_after_calls",
        "mutate_relation",
        "path",
        "slot_count",
    )

    def __init__(
        self,
        path: Path,
        slot_count: int = 3,
        kill_after_calls: int | None = None,
        *,
        mutate_relation: bool = False,
    ) -> None:
        self.path = path
        self.slot_count = slot_count
        self.kill_after_calls = kill_after_calls
        self.mutate_relation = mutate_relation
        self.calls = 0

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        self.calls += 1
        if self.mutate_relation and self.calls == 1:
            with connect(self.path) as connection:
                _ = query(
                    connection,
                    """UPDATE relation_snapshots
                       SET relation_content_sha = ? WHERE id = 10""",
                    ("e" * 64,),
                )
        if self.kill_after_calls == self.calls:
            raise SimulatedHardKillError
        return tuple(payload(anchor_id, slot) for slot in range(1, self.slot_count + 1))


def payload(anchor_id: str, slot: int) -> CachePayload:
    return CachePayload(
        {
            "anchor_id": anchor_id,
            "candidate_id": f"C-{slot}",
            "matched_quantities": [],
            "missing_reasons": [],
            "schema_version": "1",
            "scores": {"S": Decimal("0.500000")},
            "slot": slot,
        }
    )


def release_database(
    path: Path,
    product_ids: tuple[str, ...] = ("A", "B"),
    *,
    candidate_id: int = 10,
    previous_id: int = 20,
) -> ReleaseFixture:
    migrate(path)
    with connect(path) as connection:
        _seed_component_graph(connection, previous_id, "old", ())
        _seed_component_graph(connection, candidate_id, "new", product_ids)
        _ = query(
            connection,
            """INSERT INTO release_bundles VALUES(
                ?, ?, ?, ?, 'v1', 0, 0, ?, ?, 'ready', 1, 1, ?, ?
            )""",
            (
                previous_id,
                previous_id,
                previous_id,
                previous_id,
                "c" * 64,
                "d" * 64,
                _iso(NOW),
                _iso(NOW),
            ),
        )
        _ = query(
            connection,
            "INSERT INTO active_release VALUES(1, ?)",
            (previous_id,),
        )
    candidate = ReleaseCandidate(candidate_id, candidate_id, candidate_id, "v1")
    return ReleaseFixture(path, candidate, previous_id)


class SimulatedHardKillError(RuntimeError):
    pass


@final
class HeartbeatKillBuilder:
    """Advance past one heartbeat and kill on the following anchor."""

    __slots__ = ("calls", "clock")

    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.calls = 0

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        self.calls += 1
        self.clock.advance(timedelta(seconds=31))
        if self.calls == 2:
            raise SimulatedHardKillError
        return tuple(payload(anchor_id, slot) for slot in range(1, 4))


def _seed_component_graph(
    connection: Connection,
    identifier: int,
    prefix: str,
    product_ids: tuple[str, ...],
) -> None:
    _ = query(
        connection,
        "INSERT INTO catalog_generations VALUES(?, ?, '{}', ?)",
        (identifier, f"catalog-{prefix}", _iso(NOW)),
    )
    _ = query(
        connection,
        "INSERT INTO attribute_snapshots VALUES(?, ?, NULL, ?, ?, 'complete', ?)",
        (identifier, identifier, len(product_ids), len(product_ids), _iso(NOW)),
    )
    _ = query(
        connection,
        """INSERT INTO materialization_snapshots VALUES(
            ?, ?, ?, ?, 'normalization-v1', 'policy-v1', 'complete', 1, ?, ?
        )""",
        (
            identifier,
            identifier,
            identifier,
            "a" * 63 + prefix[0],
            _iso(NOW),
            _iso(NOW),
        ),
    )
    for product_id in product_ids:
        _ = query(
            connection,
            """INSERT INTO products VALUES(
               ?, ?, '46', '4601', '영상감시장치', '영상감시장치', 1, ?
            )""",
            (identifier, product_id, _iso(NOW)),
        )
    _ = query(
        connection,
        "INSERT INTO index_versions VALUES(?, ?, ?, ?, 'complete', ?)",
        (identifier, identifier, "b" * 64, "c" * 64, _iso(NOW)),
    )
    _ = query(
        connection,
        "INSERT INTO relation_snapshots VALUES(?, ?, ?, 'complete', ?)",
        (identifier, "d" * 63 + prefix[0], "e" * 63 + prefix[0], _iso(NOW)),
    )


def _iso(value: datetime) -> str:
    return value.isoformat()
