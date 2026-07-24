"""Release attempt claiming, heartbeat, retry, and partial-cache writes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.ranking.cache import CacheRow, canonical_payload

from .connection import connect
from .release_types import (
    BundleRecord,
    BundleStatus,
    ReleaseKey,
    ReleaseStoreError,
    key_values,
)
from .sql import as_int, as_text, query

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path
    from sqlite3 import Connection

ACTIVE_IMMUTABLE: Final = "active-release-immutable"
BUNDLE_ID_MISSING: Final = "bundle-id-missing"
BUNDLE_STATUS_CORRUPTION: Final = "bundle-status-corruption"


@dataclass(frozen=True, slots=True)
class ReleaseAttemptStore:
    """Own release build state transitions before atomic publication."""

    database: Path

    def claim(self, key: ReleaseKey, now: datetime, cutoff: datetime) -> BundleRecord:
        """Recover stale builds and claim or replay the unique tuple."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            try:
                _recover(connection, cutoff.isoformat())
                record = _find(connection, key)
                if record is None:
                    record = _insert(connection, key, now.isoformat())
                elif record.status is BundleStatus.FAILED:
                    _require_inactive(connection, record.bundle_id)
                    record = _retry(connection, record, now.isoformat())
                _ = query(connection, "COMMIT")
            except (sqlite3.DatabaseError, ReleaseStoreError):
                _ = query(connection, "ROLLBACK")
                raise
            else:
                return record

    def set_expected(self, record: BundleRecord, expected: int, now: datetime) -> None:
        """Persist exact anchor-times-three cardinality before work begins."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """UPDATE release_bundles SET expected_cache_rows=?,heartbeat_at=?
                   WHERE id=? AND attempt_no=? AND status='building'""",
                (expected, now.isoformat(), record.bundle_id, record.attempt_no),
            )

    def write(self, record: BundleRecord, row: CacheRow) -> None:
        """Persist one canonical current-attempt cache row."""
        payload_json, payload_sha = canonical_payload(row.payload)
        with connect(self.database) as connection:
            _ = query(
                connection,
                "INSERT INTO comparator_cache VALUES(?, ?, ?, ?, ?, ?)",
                (
                    record.bundle_id,
                    record.attempt_no,
                    row.anchor_id,
                    row.slot,
                    payload_json,
                    payload_sha,
                ),
            )

    def heartbeat(self, record: BundleRecord, now: datetime) -> None:
        """Refresh ownership for a still-building attempt."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """UPDATE release_bundles SET heartbeat_at=?
                   WHERE id=? AND attempt_no=? AND status='building'""",
                (now.isoformat(), record.bundle_id, record.attempt_no),
            )

    def fail(self, record: BundleRecord, now: datetime) -> None:
        """Fail only the inactive current attempt while retaining last-good."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """UPDATE release_bundles SET status='failed',heartbeat_at=?
                   WHERE id=? AND attempt_no=? AND status='building'
                     AND NOT EXISTS(
                       SELECT 1 FROM active_release
                       WHERE bundle_id=release_bundles.id
                     )""",
                (now.isoformat(), record.bundle_id, record.attempt_no),
            )


def _recover(connection: Connection, cutoff: str) -> None:
    _ = query(
        connection,
        """UPDATE release_bundles SET status='failed'
           WHERE status='building' AND heartbeat_at<=?
             AND NOT EXISTS(
               SELECT 1 FROM active_release WHERE bundle_id=release_bundles.id
             )""",
        (cutoff,),
    )
    _ = query(
        connection,
        """UPDATE materialization_snapshots SET status='failed'
           WHERE status='building' AND heartbeat_at<=?""",
        (cutoff,),
    )


def _find(connection: Connection, key: ReleaseKey) -> BundleRecord | None:
    row = query(
        connection,
        """SELECT id,status,attempt_no,expected_cache_rows,written_cache_rows,
                  cache_content_sha,release_bundle_sha,ready_attempt_no
           FROM release_bundles
           WHERE materialization_id=? AND index_version_id=?
             AND relation_snapshot_id=? AND ranking_version=?
             AND slot_policy_version=?""",
        key_values(key),
    ).fetchone()
    return None if row is None else _record(row)


def _insert(connection: Connection, key: ReleaseKey, now: str) -> BundleRecord:
    cursor = query(
        connection,
        """INSERT INTO release_bundles(
             materialization_id,index_version_id,relation_snapshot_id,
             ranking_version,slot_policy_version,expected_cache_rows,
             written_cache_rows,cache_content_sha,release_bundle_sha,status,
             attempt_no,ready_attempt_no,heartbeat_at,created_at
           ) VALUES(?,?,?,?,?,0,0,NULL,NULL,'building',1,NULL,?,?)""",
        (*key_values(key), now, now),
    )
    if cursor.lastrowid is None:
        raise ReleaseStoreError(BUNDLE_ID_MISSING)
    return _building(cursor.lastrowid, 1)


def _retry(connection: Connection, record: BundleRecord, now: str) -> BundleRecord:
    attempt = record.attempt_no + 1
    _ = query(
        connection,
        """UPDATE release_bundles SET status='building',attempt_no=?,
           expected_cache_rows=0,written_cache_rows=0,cache_content_sha=NULL,
           release_bundle_sha=NULL,ready_attempt_no=NULL,heartbeat_at=?
           WHERE id=?""",
        (attempt, now, record.bundle_id),
    )
    return _building(record.bundle_id, attempt)


def _building(bundle_id: int, attempt: int) -> BundleRecord:
    return BundleRecord(
        bundle_id,
        BundleStatus.BUILDING,
        attempt,
        0,
        0,
        None,
        None,
        None,
        owned=True,
    )


def _require_inactive(connection: Connection, bundle_id: int) -> None:
    active = query(
        connection,
        "SELECT 1 FROM active_release WHERE bundle_id=?",
        (bundle_id,),
    ).fetchone()
    if active is not None:
        raise ReleaseStoreError(ACTIVE_IMMUTABLE)


def _record(row: tuple[str | int | float | bytes | None, ...]) -> BundleRecord:
    try:
        status = BundleStatus(as_text(row[1]))
    except ValueError as error:
        raise ReleaseStoreError(BUNDLE_STATUS_CORRUPTION) from error
    return BundleRecord(
        as_int(row[0]),
        status,
        as_int(row[2]),
        as_int(row[3]),
        as_int(row[4]),
        None if row[5] is None else as_text(row[5]),
        None if row[6] is None else as_text(row[6]),
        None if row[7] is None else as_int(row[7]),
        owned=False,
    )
