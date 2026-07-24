"""SQLite repository for release graph validation and atomic publication."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .connection import connect
from .release_attempt import ReleaseAttemptStore
from .release_types import (
    BundleRecord,
    ReadyValues,
    ReleaseKey,
    ReleaseStoreError,
    key_values,
)
from .release_validation import (
    ReleaseComponents,
    ReleaseHashInput,
    active_anchors,
    load_components,
    release_bundle_sha,
    validate_cache,
)
from .sql import as_int, query

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path
    from sqlite3 import Connection

    from g2b_compare.ranking.cache import CacheRow

COMPONENT_DRIFT: Final = "component-drift"
READY_CORRUPTION: Final = "ready-corruption"
STALE_RELEASE_ATTEMPT: Final = "stale-release-attempt"
RELEASE_CARDINALITY_DRIFT: Final = "release-cardinality-drift"


@dataclass(frozen=True, slots=True)
class ReleaseStore:
    """Coordinate attempt persistence with final graph publication."""

    database: Path

    def claim(self, key: ReleaseKey, now: datetime, cutoff: datetime) -> BundleRecord:
        """Claim or replay the unique release tuple."""
        return ReleaseAttemptStore(self.database).claim(key, now, cutoff)

    def components(self, key: ReleaseKey) -> ReleaseComponents:
        """Read the complete candidate component identity."""
        with connect(self.database) as connection:
            try:
                return load_components(connection, *key_values(key)[:3])
            except ValueError as error:
                raise ReleaseStoreError(str(error)) from error

    def anchors(self, materialization_id: int) -> tuple[str, ...]:
        """Read active anchors for exact cache cardinality."""
        with connect(self.database) as connection:
            return active_anchors(connection, materialization_id)

    def set_expected(self, record: BundleRecord, expected: int, now: datetime) -> None:
        """Persist exact expected cache cardinality."""
        ReleaseAttemptStore(self.database).set_expected(record, expected, now)

    def write(self, record: BundleRecord, row: CacheRow) -> None:
        """Persist one current-attempt cache row."""
        ReleaseAttemptStore(self.database).write(record, row)

    def heartbeat(self, record: BundleRecord, now: datetime) -> None:
        """Refresh current attempt ownership."""
        ReleaseAttemptStore(self.database).heartbeat(record, now)

    def fail(self, record: BundleRecord, now: datetime) -> None:
        """Fail one inactive current attempt."""
        ReleaseAttemptStore(self.database).fail(record, now)

    def publish(
        self,
        key: ReleaseKey,
        record: BundleRecord,
        original: ReleaseComponents,
        now: datetime,
    ) -> None:
        """Verify and atomically ready the candidate plus singleton pointer."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            try:
                current = load_components(connection, *key_values(key)[:3])
                _require_same_components(current, original)
                cache_sha, written = validate_cache(
                    connection,
                    key.materialization_id,
                    record.bundle_id,
                    record.attempt_no,
                )
                _require_expected_cardinality(connection, record, written)
                bundle_sha = release_bundle_sha(
                    ReleaseHashInput(
                        components=current,
                        ranking_version=key.ranking_version,
                        expected_cache_rows=written,
                        cache_content_sha=cache_sha,
                        slot_policy_version=key.slot_policy_version,
                    )
                )
                _ready(
                    connection,
                    record,
                    ReadyValues(written, cache_sha, bundle_sha, now),
                )
                _ = query(
                    connection,
                    """DELETE FROM comparator_cache
                       WHERE release_bundle_id=? AND attempt_no<>?""",
                    (record.bundle_id, record.attempt_no),
                )
                _ = query(
                    connection,
                    """INSERT INTO active_release VALUES(1, ?)
                       ON CONFLICT(singleton) DO UPDATE
                       SET bundle_id=excluded.bundle_id""",
                    (record.bundle_id,),
                )
                _ = query(connection, "COMMIT")
            except ValueError as error:
                _ = query(connection, "ROLLBACK")
                raise ReleaseStoreError(str(error)) from error
            except (sqlite3.DatabaseError, ReleaseStoreError):
                _ = query(connection, "ROLLBACK")
                raise

    def verify_ready(self, key: ReleaseKey, record: BundleRecord) -> None:
        """Fail closed unless a ready tuple is byte-identical and complete."""
        try:
            with connect(self.database) as connection:
                component = load_components(connection, *key_values(key)[:3])
                cache_sha, written = validate_cache(
                    connection,
                    key.materialization_id,
                    record.bundle_id,
                    record.attempt_no,
                )
        except ValueError as error:
            raise ReleaseStoreError(READY_CORRUPTION) from error
        bundle_sha = release_bundle_sha(
            ReleaseHashInput(
                components=component,
                ranking_version=key.ranking_version,
                expected_cache_rows=written,
                cache_content_sha=cache_sha,
                slot_policy_version=key.slot_policy_version,
            )
        )
        observed = (
            record.ready_attempt_no,
            record.expected_rows,
            record.written_rows,
            record.cache_sha,
            record.bundle_sha,
        )
        expected = (record.attempt_no, written, written, cache_sha, bundle_sha)
        if observed != expected:
            raise ReleaseStoreError(READY_CORRUPTION)


def _ready(
    connection: Connection,
    record: BundleRecord,
    values: ReadyValues,
) -> None:
    cursor = query(
        connection,
        """UPDATE release_bundles
           SET written_cache_rows=?,cache_content_sha=?,release_bundle_sha=?,
               status='ready',ready_attempt_no=attempt_no,heartbeat_at=?
           WHERE id=? AND attempt_no=? AND status='building'""",
        (
            values.written,
            values.cache_sha,
            values.bundle_sha,
            values.now.isoformat(),
            record.bundle_id,
            record.attempt_no,
        ),
    )
    if cursor.rowcount != 1:
        raise ReleaseStoreError(STALE_RELEASE_ATTEMPT)


def _require_same_components(
    current: ReleaseComponents,
    original: ReleaseComponents,
) -> None:
    if current != original:
        raise ReleaseStoreError(COMPONENT_DRIFT)


def _require_expected_cardinality(
    connection: Connection,
    record: BundleRecord,
    written: int,
) -> None:
    row = query(
        connection,
        """SELECT expected_cache_rows FROM release_bundles
           WHERE id=? AND attempt_no=? AND status='building'""",
        (record.bundle_id, record.attempt_no),
    ).fetchone()
    if row is None:
        raise ReleaseStoreError(STALE_RELEASE_ATTEMPT)
    if as_int(row[0]) != written:
        raise ReleaseStoreError(RELEASE_CARDINALITY_DRIFT)
