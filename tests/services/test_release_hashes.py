from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_text, query
from g2b_compare.ranking.cache import CachePayload
from g2b_compare.services.release import (
    ComparatorCacheBuilder,
    ReleaseCandidate,
    ReleaseContractError,
    ReleaseCoordinator,
)
from tests.services.release_support import (
    MutableClock,
    PayloadBuilder,
    payload,
    release_database,
)

if TYPE_CHECKING:
    from pathlib import Path

CACHE_GOLDEN = "d54508ae23788d71648cbec61333f3eace5b1d539352c16625525f3d29da9e6b"
BUNDLE_GOLDEN = "5c71c1db667f1650fb0b54815a75fe9d8c2c201d84bc524756eb33313deaf45e"


@dataclass(frozen=True, slots=True)
class HashObservation:
    left_cache: str
    left_bundle: str
    right_cache: str
    right_bundle: str
    policy_drift: str
    cardinality_drift: str
    schema_drift: str


@final
class DriftBuilder:
    __slots__ = ("drift", "path")

    def __init__(self, path: Path, drift: str) -> None:
        self.path = path
        self.drift = drift

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        if self.drift == "cardinality" and anchor_id == "A":
            with connect(self.path) as connection:
                statement = (
                    "UPDATE release_bundles SET expected_cache_rows=5 "
                    "WHERE materialization_id=10 AND status='building'"
                )
                _ = query(connection, statement)
        schema = "2" if self.drift == "schema" else "1"
        return tuple(_payload(anchor_id, slot, schema) for slot in range(1, 4))


def test_release_bundle_hash_is_semantic_and_drift_fails_closed(
    tmp_path: Path,
) -> None:
    # Given: semantically equal releases use different SQLite component IDs.
    left = release_database(tmp_path / "left.sqlite3")
    right = release_database(
        tmp_path / "right.sqlite3",
        candidate_id=110,
        previous_id=120,
    )
    left_ready = ReleaseCoordinator(left.path, MutableClock()).coordinate(
        left.candidate,
        PayloadBuilder(left.path),
    )
    right_ready = ReleaseCoordinator(right.path, MutableClock()).coordinate(
        right.candidate,
        PayloadBuilder(right.path),
    )
    left_hashes = _hashes(left.path, left_ready.bundle_id)
    right_hashes = _hashes(right.path, right_ready.bundle_id)

    # When: policy, exact cardinality, and payload schema are drifted independently.
    policy = release_database(tmp_path / "policy.sqlite3")
    policy_coordinator = ReleaseCoordinator(policy.path, MutableClock())
    policy_ready = policy_coordinator.coordinate(
        policy.candidate,
        PayloadBuilder(policy.path),
    )
    with connect(policy.path) as connection:
        _ = query(
            connection,
            "UPDATE active_release SET bundle_id=?",
            (policy.previous_bundle_id,),
        )
        _ = query(
            connection,
            """UPDATE materialization_snapshots
               SET materialization_policy_version='policy-v2' WHERE id=10""",
        )
    policy_drift = _coordinate_outcome(
        policy_coordinator,
        policy.candidate,
        PayloadBuilder(policy.path),
    )
    cardinality = release_database(tmp_path / "cardinality.sqlite3")
    cardinality_drift = _coordinate_outcome(
        ReleaseCoordinator(cardinality.path, MutableClock()),
        cardinality.candidate,
        DriftBuilder(cardinality.path, "cardinality"),
    )
    schema = release_database(tmp_path / "schema.sqlite3")
    schema_drift = _coordinate_outcome(
        ReleaseCoordinator(schema.path, MutableClock()),
        schema.candidate,
        DriftBuilder(schema.path, "schema"),
    )

    # Then: exact golden identity is DB-ID independent and every drift fails closed.
    observed = HashObservation(
        left_hashes[0],
        left_hashes[1],
        right_hashes[0],
        right_hashes[1],
        policy_drift,
        cardinality_drift,
        schema_drift,
    )
    assert observed == HashObservation(
        CACHE_GOLDEN,
        BUNDLE_GOLDEN,
        CACHE_GOLDEN,
        BUNDLE_GOLDEN,
        "ready-corruption",
        "release-cardinality-drift",
        "cache-payload-schema",
    )
    assert policy_ready.bundle_id > 0


def _coordinate_outcome(
    coordinator: ReleaseCoordinator,
    candidate: ReleaseCandidate,
    builder: ComparatorCacheBuilder,
) -> str:
    try:
        result = coordinator.coordinate(candidate, builder)
    except ReleaseContractError as error:
        return error.code
    except sqlite3.IntegrityError:
        return "sqlite-integrity"
    return result.disposition.value


def _hashes(path: Path, bundle_id: int) -> tuple[str, str]:
    with connect(path) as connection:
        row = query(
            connection,
            """SELECT cache_content_sha,release_bundle_sha FROM release_bundles
               WHERE id=?""",
            (bundle_id,),
        ).fetchone()
    assert row is not None
    return as_text(row[0]), as_text(row[1])


def _payload(anchor_id: str, slot: int, schema: str) -> CachePayload:
    if schema == "1":
        return payload(anchor_id, slot)
    return CachePayload(
        {
            "anchor_id": anchor_id,
            "candidate_id": f"C-{slot}",
            "matched_quantities": [],
            "missing_reasons": [],
            "schema_version": schema,
            "scores": {"S": "0.500000"},
            "slot": slot,
        }
    )
