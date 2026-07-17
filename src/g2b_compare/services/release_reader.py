"""Request-scoped ready-release pins and canonical cache reads."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import SqlRow, as_int, as_text, query
from g2b_compare.ranking.cache import (
    CacheContractError,
    CachedSlot,
    CachePayload,
    canonical_payload,
)

from .release_models import ReleaseContractError, ReleasePin

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator
    from pathlib import Path

PIN_DRIFT: Final = "release-pin-drift"
CACHE_CORRUPTION: Final = "cache-corruption"
NO_READY_RELEASE: Final = "no-ready-release"


def pin_active_release(database: Path) -> ReleasePin:
    """Pin the ready bundle and attempt at request start."""
    return _pin_release(database, None, require_active=True)


def pin_release_bundle(database: Path, bundle_id: int) -> ReleasePin:
    """Pin one known ready bundle without consulting the active pointer."""
    return _pin_release(database, bundle_id, require_active=False)


@contextmanager
def open_release_reader(
    database: Path,
    pin: ReleasePin,
) -> Generator[sqlite3.Connection]:
    """Open one query-only SQLite snapshot bound to a release pin."""
    with connect_read_only(database) as connection:
        _ = query(connection, "BEGIN")
        try:
            if (
                _pin_from_connection(
                    connection,
                    pin.bundle_id,
                    require_active=False,
                )
                != pin
            ):
                raise ReleaseContractError(PIN_DRIFT)
            yield connection
        finally:
            _ = query(connection, "ROLLBACK")


def read_anchor_payloads(
    database: Path,
    pin: ReleasePin,
    anchor_id: str,
) -> tuple[CachedSlot, CachedSlot, CachedSlot] | None:
    """Read exactly three verified cache slots from the pinned attempt."""
    with open_release_reader(database, pin) as connection:
        rows = query(
            connection,
            """SELECT slot,payload_json,payload_sha FROM comparator_cache
               WHERE release_bundle_id=? AND attempt_no=? AND anchor_id=?
               ORDER BY slot""",
            (pin.bundle_id, pin.ready_attempt_no, anchor_id),
        ).fetchall()
    if not rows:
        return None
    if tuple(as_int(row[0]) for row in rows) != (1, 2, 3):
        raise ReleaseContractError(CACHE_CORRUPTION)
    slots: list[CachedSlot] = []
    for row in rows:
        try:
            payload = CachePayload.model_validate_json(as_text(row[1]))
            document, digest = canonical_payload(payload)
        except (ValidationError, CacheContractError) as error:
            raise ReleaseContractError(CACHE_CORRUPTION) from error
        if document != as_text(row[1]) or digest != as_text(row[2]):
            raise ReleaseContractError(CACHE_CORRUPTION)
        slots.append(CachedSlot(as_int(row[0]), payload, document, digest))
    return slots[0], slots[1], slots[2]


def _pin_release(
    database: Path,
    bundle_id: int | None,
    *,
    require_active: bool,
) -> ReleasePin:
    with connect_read_only(database) as connection:
        return _pin_from_connection(
            connection,
            bundle_id,
            require_active=require_active,
        )


def _pin_from_connection(
    connection: sqlite3.Connection,
    bundle_id: int | None,
    *,
    require_active: bool,
) -> ReleasePin:
    row = (
        _active_pin_row(connection)
        if require_active
        else _bundle_pin_row(connection, bundle_id)
    )
    if row is None or row[1] is None:
        raise ReleaseContractError(NO_READY_RELEASE)
    return ReleasePin(
        as_int(row[0]),
        as_int(row[1]),
        as_int(row[2]),
        as_int(row[3]),
        as_int(row[4]),
        as_text(row[5]),
        as_text(row[6]),
        as_text(row[7]),
        as_text(row[8]),
        as_text(row[9]),
        as_text(row[10]),
        as_text(row[11]),
        as_text(row[12]),
        as_text(row[13]),
    )


def _active_pin_row(connection: sqlite3.Connection) -> SqlRow | None:
    return query(connection, _ACTIVE_PIN_QUERY).fetchone()


def _bundle_pin_row(
    connection: sqlite3.Connection,
    bundle_id: int | None,
) -> SqlRow | None:
    if bundle_id is None:
        return None
    return query(connection, _BUNDLE_PIN_QUERY, (bundle_id,)).fetchone()


_ACTIVE_PIN_QUERY: Final = """SELECT b.id,b.ready_attempt_no,b.materialization_id,
b.index_version_id,b.relation_snapshot_id,b.ranking_version,
m.normalization_version,m.materialization_policy_version,
m.materialization_source_sha,i.index_artifact_sha,
i.index_manifest_sha,r.source_manifest_sha,r.relation_content_sha,
COALESCE(MAX(p.data_as_of),'') FROM release_bundles b
JOIN active_release ar ON ar.bundle_id=b.id
JOIN materialization_snapshots m ON m.id=b.materialization_id
JOIN index_versions i ON i.id=b.index_version_id
JOIN relation_snapshots r ON r.id=b.relation_snapshot_id
LEFT JOIN products p ON p.materialization_id=m.id AND p.active=1
WHERE b.status='ready' AND b.ready_attempt_no=b.attempt_no GROUP BY b.id"""

_BUNDLE_PIN_QUERY: Final = """SELECT b.id,b.ready_attempt_no,b.materialization_id,
b.index_version_id,b.relation_snapshot_id,b.ranking_version,
m.normalization_version,m.materialization_policy_version,
m.materialization_source_sha,i.index_artifact_sha,
i.index_manifest_sha,r.source_manifest_sha,r.relation_content_sha,
COALESCE(MAX(p.data_as_of),'') FROM release_bundles b
JOIN materialization_snapshots m ON m.id=b.materialization_id
JOIN index_versions i ON i.id=b.index_version_id
JOIN relation_snapshots r ON r.id=b.relation_snapshot_id
LEFT JOIN products p ON p.materialization_id=m.id AND p.active=1
WHERE b.status='ready' AND b.ready_attempt_no=b.attempt_no AND b.id=?
GROUP BY b.id"""
