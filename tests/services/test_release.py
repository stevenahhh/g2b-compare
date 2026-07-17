from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.services.release import (
    ReleaseContractError,
    ReleaseCoordinator,
    ReleaseDisposition,
    open_release_reader,
    pin_active_release,
    read_anchor_payloads,
)
from tests.services.release_support import (
    MutableClock,
    PayloadBuilder,
    SimulatedHardKillError,
    release_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_complete_candidate_publishes_exact_anchor_times_three_cache(
    tmp_path: Path,
) -> None:
    # Given: a complete inactive two-anchor candidate and a prior active release.
    fixture = release_database(tmp_path / "release.sqlite3")
    coordinator = ReleaseCoordinator(fixture.path, MutableClock())

    # When: every anchor receives exactly three canonical comparator slots.
    result = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    pin = pin_active_release(fixture.path)
    slots = read_anchor_payloads(fixture.path, pin, "A")

    # Then: one ready attempt is atomically active with exact cardinality and slots.
    assert result.disposition is ReleaseDisposition.READY
    assert pin.bundle_id == result.bundle_id
    assert pin.ready_attempt_no == 1
    assert slots is not None
    assert tuple(slot.slot for slot in slots) == (1, 2, 3)
    with connect(fixture.path) as connection:
        row = query(
            connection,
            """SELECT expected_cache_rows, written_cache_rows, status
               FROM release_bundles WHERE id = ?""",
            (pin.bundle_id,),
        ).fetchone()
    assert row == (6, 6, "ready")


@pytest.mark.parametrize(
    ("statement", "code"),
    [
        (
            "UPDATE materialization_snapshots SET status='failed' WHERE id=10",
            "materialization-incomplete",
        ),
        ("UPDATE index_versions SET status='failed' WHERE id=10", "index-incomplete"),
        (
            "UPDATE relation_snapshots SET status='failed' WHERE id=10",
            "relation-incomplete",
        ),
    ],
)
def test_incomplete_component_fails_candidate_and_retains_previous_active(
    tmp_path: Path,
    statement: str,
    code: str,
) -> None:
    # Given: one required candidate component is incomplete.
    fixture = release_database(tmp_path / f"{code}.sqlite3")
    with connect(fixture.path) as connection:
        _ = query(connection, statement)

    # When: release coordination validates the exact graph.
    with pytest.raises(ReleaseContractError, match=code):
        _ = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
            fixture.candidate,
            PayloadBuilder(fixture.path),
        )

    # Then: the candidate is failed and the previous active pointer is unchanged.
    with connect(fixture.path) as connection:
        pointer = query(connection, "SELECT bundle_id FROM active_release").fetchone()
        status = query(
            connection,
            "SELECT status FROM release_bundles WHERE materialization_id=10",
        ).fetchone()
    assert pointer == (fixture.previous_bundle_id,)
    assert status == ("failed",)


def test_cache_short_and_component_drift_fail_without_pointer_swap(
    tmp_path: Path,
) -> None:
    # Given: independent complete candidates whose cache or relation changes mid-build.
    short = release_database(tmp_path / "short.sqlite3")
    drift = release_database(tmp_path / "drift.sqlite3")

    # When: one build writes only two slots and one mutates a component SHA.
    with pytest.raises(ReleaseContractError, match="cache-cardinality"):
        _ = ReleaseCoordinator(short.path, MutableClock()).coordinate(
            short.candidate,
            PayloadBuilder(short.path, slot_count=2),
        )
    with pytest.raises(ReleaseContractError, match="component-drift"):
        _ = ReleaseCoordinator(drift.path, MutableClock()).coordinate(
            drift.candidate,
            PayloadBuilder(drift.path, mutate_relation=True),
        )

    # Then: neither candidate replaces its last-good active release.
    for fixture in (short, drift):
        with connect(fixture.path) as connection:
            pointer = query(
                connection, "SELECT bundle_id FROM active_release"
            ).fetchone()
        assert pointer == (fixture.previous_bundle_id,)


def test_hard_kill_recovery_preserves_0959_and_retries_at_1000(tmp_path: Path) -> None:
    # Given: attempt one is killed after leaving partial current-attempt cache rows.
    fixture = release_database(tmp_path / "retry.sqlite3")
    clock = MutableClock()
    coordinator = ReleaseCoordinator(fixture.path, clock)
    with pytest.raises(SimulatedHardKillError):
        _ = coordinator.coordinate(
            fixture.candidate,
            PayloadBuilder(fixture.path, kill_after_calls=2),
        )

    # When: recovery runs at 9:59 and then at the exact 10:00 boundary.
    clock.advance(timedelta(minutes=9, seconds=59))
    pending = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    clock.advance(timedelta(seconds=1))
    ready = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))

    # Then: recent attempt stays; retry two becomes ready and attempt one is pruned.
    assert pending.disposition is ReleaseDisposition.BUILDING_NOOP
    assert ready.disposition is ReleaseDisposition.READY
    assert ready.attempt_no == 2
    with connect(fixture.path) as connection:
        bundle = query(
            connection,
            """SELECT attempt_no, ready_attempt_no, written_cache_rows
               FROM release_bundles WHERE id=?""",
            (ready.bundle_id,),
        ).fetchone()
        attempts = query(
            connection,
            """SELECT DISTINCT attempt_no FROM comparator_cache
               WHERE release_bundle_id=?""",
            (ready.bundle_id,),
        ).fetchall()
    assert bundle == (2, 2, 6)
    assert attempts == [(2,)]


def test_ready_identical_is_byte_noop_and_corruption_is_rejected(
    tmp_path: Path,
) -> None:
    # Given: a published candidate bundle.
    fixture = release_database(tmp_path / "noop.sqlite3")
    coordinator = ReleaseCoordinator(fixture.path, MutableClock())
    ready = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    before = _bundle_bytes(fixture.path, ready.bundle_id)

    # When: the identical tuple is coordinated again.
    noop = coordinator.coordinate(
        fixture.candidate, PayloadBuilder(fixture.path, kill_after_calls=1)
    )

    # Then: no builder call or field/pointer update occurs.
    assert noop.disposition is ReleaseDisposition.READY_NOOP
    assert before == _bundle_bytes(fixture.path, ready.bundle_id)

    # When: the inactive ready cache is corrupted before replay.
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
        _ = query(
            connection,
            """UPDATE comparator_cache SET payload_sha=?
               WHERE release_bundle_id=? AND slot=1""",
            ("0" * 64, ready.bundle_id),
        )
    with pytest.raises(ReleaseContractError, match="ready-corruption"):
        _ = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))


def test_release_pin_reader_survives_later_pointer_swap_and_rejects_cache_drift(
    tmp_path: Path,
) -> None:
    # Given: a request pins one complete ready attempt.
    fixture = release_database(tmp_path / "pin.sqlite3")
    ready = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
        fixture.candidate,
        PayloadBuilder(fixture.path),
    )
    pin = pin_active_release(fixture.path)

    # When: a later request swaps the singleton pointer back to another valid bundle.
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
    with open_release_reader(fixture.path, pin) as reader:
        row = query(
            reader, "SELECT id FROM release_bundles WHERE id=?", (ready.bundle_id,)
        ).fetchone()

    # Then: the original request still reads its exact frozen graph.
    assert row == (ready.bundle_id,)
    assert read_anchor_payloads(fixture.path, pin, "B") is not None

    # When/Then: incomplete pinned slots fail closed rather than mixing attempts.
    with connect(fixture.path) as connection:
        _ = query(
            connection,
            """DELETE FROM comparator_cache WHERE release_bundle_id=?
               AND anchor_id='B' AND slot=3""",
            (ready.bundle_id,),
        )
    with pytest.raises(ReleaseContractError, match="cache-corruption"):
        _ = read_anchor_payloads(fixture.path, pin, "B")


def test_active_bundle_rows_are_immutable_at_database_boundary(tmp_path: Path) -> None:
    # Given: the newly ready candidate is active.
    fixture = release_database(tmp_path / "immutable.sqlite3")
    ready = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
        fixture.candidate,
        PayloadBuilder(fixture.path),
    )

    # When/Then: neither retry state nor active pointer-owned cache can be mutated.
    with connect(fixture.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            _ = query(
                connection,
                "UPDATE release_bundles SET status='failed' WHERE id=?",
                (ready.bundle_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            _ = query(
                connection,
                "DELETE FROM comparator_cache WHERE release_bundle_id=?",
                (ready.bundle_id,),
            )


def _bundle_bytes(path: Path, bundle_id: int) -> bytes:
    with connect(path) as connection:
        bundle = query(
            connection,
            "SELECT * FROM release_bundles WHERE id=?",
            (bundle_id,),
        ).fetchone()
        pointer = query(connection, "SELECT * FROM active_release").fetchone()
        cache = query(
            connection,
            """SELECT * FROM comparator_cache WHERE release_bundle_id=?
               ORDER BY attempt_no, anchor_id, slot""",
            (bundle_id,),
        ).fetchall()
    assert bundle is not None
    return repr(
        (
            tuple(
                as_text(value)
                if isinstance(value, str)
                else as_int(value)
                if isinstance(value, int)
                else value
                for value in bundle
            ),
            pointer,
            cache,
        )
    ).encode()
