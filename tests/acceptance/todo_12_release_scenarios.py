from __future__ import annotations

import sqlite3
from datetime import timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Final, Protocol

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.importers.workbook_relations import (
    PINNED_FILENAME,
    import_workbook_relations,
)
from g2b_compare.ranking.cache import CachePayload, canonical_payload
from g2b_compare.services.release import (
    ReleaseCoordinator,
    pin_active_release,
    read_anchor_payloads,
)
from tests.acceptance.todo_12_release_support import (
    MutationBuilder,
    candidate_attempt,
    killed_attempt,
    ready_after_retry,
    ready_candidate,
    release_error,
    result_observation,
)
from tests.services.release_support import (
    MutableClock,
    PayloadBuilder,
    SimulatedHardKillError,
    release_database,
)


class ScenarioRoute(Protocol):
    def __call__(self, path: Path, /) -> tuple[str, str]: ...


def observe_release(scenario: str, tmp_path: Path) -> tuple[str, str]:
    route = ROUTES.get(scenario)
    assert route is not None, scenario
    return route(tmp_path)


def _kill_before_swap(tmp_path: Path) -> tuple[str, str]:
    fixture = release_database(tmp_path / "kill.sqlite3")
    try:
        _ = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
            fixture.candidate,
            PayloadBuilder(fixture.path, kill_after_calls=2),
        )
    except SimulatedHardKillError:
        pin = pin_active_release(fixture.path)
        return type(pin).__name__, f"active-bundle={pin.bundle_id}"
    raise AssertionError


def _orphan_0959(tmp_path: Path) -> tuple[str, str]:
    fixture, clock, coordinator = killed_attempt(tmp_path / "orphan-0959.sqlite3")
    clock.advance(timedelta(minutes=9, seconds=59))
    result = coordinator.coordinate(fixture.candidate, PayloadBuilder(fixture.path))
    return result_observation(result)


def _retry_result(tmp_path: Path) -> tuple[str, str]:
    _, result = ready_after_retry(tmp_path / "retry.sqlite3")
    return result_observation(result)


def _build_error(
    tmp_path: Path,
    *,
    slot_count: int,
) -> tuple[str, str]:
    fixture = release_database(tmp_path / "cache-short.sqlite3")
    builder = PayloadBuilder(fixture.path, slot_count=slot_count)
    return release_error(fixture, builder)


def _component_drift(
    tmp_path: Path,
    *,
    component: str,
) -> tuple[str, str]:
    fixture = release_database(tmp_path / f"{component}-drift.sqlite3")
    statements = {
        "index": "UPDATE index_versions SET index_artifact_sha='drift' WHERE id=10",
        "relation": (
            "UPDATE relation_snapshots SET relation_content_sha='drift' WHERE id=10"
        ),
    }
    statement = statements[component]
    return release_error(fixture, MutationBuilder(fixture.path, statement))


def _relation_import(tmp_path: Path) -> tuple[str, str]:
    fixture = release_database(tmp_path / "relation-import.sqlite3")
    before = pin_active_release(fixture.path)
    imported = import_workbook_relations(Path("dataset") / PINNED_FILENAME)
    after = pin_active_release(fixture.path)
    assert before == after
    return (
        type(imported).__name__,
        f"active-bundle={after.bundle_id}; relations={len(imported.relations)}",
    )


def _request_pin(tmp_path: Path) -> tuple[str, str]:
    fixture, ready = ready_candidate(tmp_path / "request-pin.sqlite3")
    pinned = pin_active_release(fixture.path)
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
    current = pin_active_release(fixture.path)
    assert read_anchor_payloads(fixture.path, pinned, "A") is not None
    assert pinned.bundle_id == ready.bundle_id
    return (
        type(pinned).__name__,
        f"pinned-bundle={pinned.bundle_id}; current-bundle={current.bundle_id}",
    )


def _stale_row_counted(tmp_path: Path) -> tuple[str, str]:
    fixture, result = ready_after_retry(tmp_path / "stale-count.sqlite3")
    with connect(fixture.path) as connection:
        row = query(
            connection,
            """SELECT expected_cache_rows,written_cache_rows
               FROM release_bundles WHERE id=?""",
            (result.bundle_id,),
        ).fetchone()
    assert row is not None
    return type(result).__name__, f"expected={as_int(row[0])}; written={as_int(row[1])}"


def _stale_row_served(tmp_path: Path) -> tuple[str, str]:
    fixture, result = ready_after_retry(tmp_path / "stale-served.sqlite3")
    pin = pin_active_release(fixture.path)
    slots = read_anchor_payloads(fixture.path, pin, "A")
    assert slots is not None
    return type(slots[0]).__name__, f"attempt={result.attempt_no}; slot={slots[0].slot}"


def _canonical_equivalence(_tmp_path: Path, *, kind: str) -> tuple[str, str]:
    pairs = {
        "key": (
            CachePayload({"z": 1, "a": 2}),
            CachePayload({"a": 2, "z": 1}),
        ),
        "decimal": (
            CachePayload({"score": Decimal("1.00")}),
            CachePayload({"score": Decimal("1.0")}),
        ),
        "array": (
            CachePayload({"values": ["first", "second"]}),
            CachePayload({"values": ["second", "first"]}),
        ),
    }
    first, second = pairs[kind]
    equal = canonical_payload(first)[1] == canonical_payload(second)[1]
    return type(first).__name__, f"sha-equal={int(equal)}"


def _ready_corruption(
    tmp_path: Path,
    *,
    mutation: str,
) -> tuple[str, str]:
    fixture, ready = ready_candidate(tmp_path / f"{mutation}-drift.sqlite3")
    statements = {
        "cache": "UPDATE release_bundles SET cache_content_sha='drift' WHERE id=?",
        "relation-content": (
            "UPDATE relation_snapshots SET relation_content_sha='drift' WHERE id=10"
        ),
        "relation-source": (
            "UPDATE relation_snapshots SET source_manifest_sha='drift' WHERE id=10"
        ),
        "bundle": "UPDATE release_bundles SET release_bundle_sha='drift' WHERE id=?",
    }
    with connect(fixture.path) as connection:
        _ = query(connection, "UPDATE active_release SET bundle_id=20")
        statement = statements[mutation]
        parameters = (ready.bundle_id,) if "WHERE id=?" in statement else ()
        _ = query(connection, statement, parameters)
    return release_error(fixture, PayloadBuilder(fixture.path))


def _ready_noop(tmp_path: Path) -> tuple[str, str]:
    fixture, _ = ready_candidate(tmp_path / "ready-noop.sqlite3")
    result = ReleaseCoordinator(fixture.path, MutableClock()).coordinate(
        fixture.candidate,
        PayloadBuilder(fixture.path, kill_after_calls=1),
    )
    return result_observation(result)


def _active_retry_rejected(tmp_path: Path) -> tuple[str, str]:
    fixture, ready = ready_candidate(tmp_path / "active-retry.sqlite3")
    try:
        with connect(fixture.path) as connection:
            _ = query(
                connection,
                "UPDATE release_bundles SET status='failed' WHERE id=?",
                (ready.bundle_id,),
            )
    except sqlite3.IntegrityError as error:
        return type(error).__name__, str(error)
    raise AssertionError


def _active_pointer_on_retry(tmp_path: Path) -> tuple[str, str]:
    fixture, clock, coordinator = killed_attempt(tmp_path / "pointer-retry.sqlite3")
    clock.advance(timedelta(minutes=10))
    try:
        _ = coordinator.coordinate(
            fixture.candidate,
            PayloadBuilder(fixture.path, kill_after_calls=1),
        )
    except SimulatedHardKillError:
        pin = pin_active_release(fixture.path)
        attempt = candidate_attempt(fixture)
        message = f"active-bundle={pin.bundle_id}; retry-attempt={attempt}"
        return type(pin).__name__, message
    raise AssertionError


ROUTES: Final[dict[str, ScenarioRoute]] = {
    "release-kill-before-swap": _kill_before_swap,
    "release-orphan-0959": _orphan_0959,
    "release-orphan-1000": _retry_result,
    "release-retry-same-tuple": _retry_result,
    "release-cache-short": partial(_build_error, slot_count=2),
    "release-index-sha-drift": partial(_component_drift, component="index"),
    "release-relation-sha-drift": partial(_component_drift, component="relation"),
    "relation-import-does-not-mutate-active": _relation_import,
    "request-bundle-pin": _request_pin,
    "stale-attempt-row-counted": _stale_row_counted,
    "stale-attempt-row-served": _stale_row_served,
    "cache-payload-key-order": partial(_canonical_equivalence, kind="key"),
    "cache-payload-decimal-equivalence": partial(
        _canonical_equivalence, kind="decimal"
    ),
    "cache-payload-array-order": partial(_canonical_equivalence, kind="array"),
    "cache-content-sha-drift": partial(_ready_corruption, mutation="cache"),
    "relation-content-sha-drift": partial(
        _ready_corruption, mutation="relation-content"
    ),
    "relation-source-manifest-sha-drift": partial(
        _ready_corruption, mutation="relation-source"
    ),
    "release-bundle-component-drift": partial(_ready_corruption, mutation="bundle"),
    "ready-same-tuple-noop": _ready_noop,
    "ready-active-retry-rejected": _active_retry_rejected,
    "active-pointer-immutable-on-retry": _active_pointer_on_retry,
}
