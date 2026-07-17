from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.release import ReleaseStore
from g2b_compare.db.release_types import (
    BundleRecord,
    BundleStatus,
    ReleaseKey,
    ReleaseStoreError,
)
from g2b_compare.db.sql import as_text, query
from g2b_compare.services.release import ReleaseCoordinator
from tests.services.release_support import (
    NOW,
    HeartbeatKillBuilder,
    MutableClock,
    PayloadBuilder,
    SimulatedHardKillError,
    release_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_build_heartbeats_after_thirty_seconds_before_hard_kill(
    tmp_path: Path,
) -> None:
    # Given: cache work crosses thirty seconds before a hard kill.
    fixture = release_database(tmp_path / "heartbeat.sqlite3")
    clock = MutableClock()

    # When: the second anchor kills after the first heartbeat interval.
    with pytest.raises(SimulatedHardKillError):
        _ = ReleaseCoordinator(fixture.path, clock).coordinate(
            fixture.candidate,
            HeartbeatKillBuilder(clock),
        )

    # Then: the partial building attempt owns a refreshed heartbeat.
    with connect(fixture.path) as connection:
        row = query(
            connection,
            """SELECT status,heartbeat_at FROM release_bundles
               WHERE materialization_id=10""",
        ).fetchone()
    assert row == ("building", (NOW + timedelta(seconds=31)).isoformat())


def test_materialization_recovery_preserves_0959_and_fails_at_1000(
    tmp_path: Path,
) -> None:
    # Given: a ready release and an unrelated building materialization orphan.
    fixture = release_database(tmp_path / "materialization-stale.sqlite3")
    clock = MutableClock()
    coordinator = ReleaseCoordinator(fixture.path, clock)
    _ = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    with connect(fixture.path) as connection:
        _ = query(
            connection,
            """INSERT INTO materialization_snapshots VALUES(
               30,10,10,?,'normalization-v1','stale-policy','building',1,?,?
            )""",
            ("f" * 64, NOW.isoformat(), NOW.isoformat()),
        )

    # When: coordinator startup runs at 9:59 and exact 10:00.
    clock.advance(timedelta(minutes=9, seconds=59))
    _ = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    recent = _materialization_status(fixture.path, 30)
    clock.advance(timedelta(seconds=1))
    _ = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))

    # Then: the recent orphan stays building; equality recovers it to failed.
    assert recent == "building"
    assert _materialization_status(fixture.path, 30) == "failed"


def test_stale_attempt_cannot_publish_after_newer_zero_anchor_ready(
    tmp_path: Path,
) -> None:
    # Given: attempt two is ready while an attempt-one worker resumes late.
    fixture = release_database(tmp_path / "stale-attempt.sqlite3", product_ids=())
    coordinator = ReleaseCoordinator(fixture.path, MutableClock())
    first = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
        _ = query(
            connection,
            "UPDATE release_bundles SET status='failed' WHERE id=?",
            (first.bundle_id,),
        )
    second = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
    key = ReleaseKey(10, 10, 10, "v1")
    store = ReleaseStore(fixture.path)
    stale = BundleRecord(
        second.bundle_id,
        BundleStatus.BUILDING,
        1,
        0,
        0,
        None,
        None,
        None,
        owned=True,
    )

    # When: the stale worker tries the final ready-and-pointer transaction.
    with pytest.raises(ReleaseStoreError, match="stale-release-attempt"):
        store.publish(key, stale, store.components(key), NOW)

    # Then: the prior active pointer remains byte-identical.
    with connect(fixture.path) as connection:
        pointer = query(connection, "SELECT bundle_id FROM active_release").fetchone()
    assert pointer == (20,)


def _materialization_status(path: Path, materialization_id: int) -> str:
    with connect(path) as connection:
        row = query(
            connection,
            "SELECT status FROM materialization_snapshots WHERE id=?",
            (materialization_id,),
        ).fetchone()
    assert row is not None
    return as_text(row[0])
