"""Predicates for work newer than the currently served release."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override

from pydantic import RootModel

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import as_int, as_text, query

PENDING: Final = "pending"
FAILED: Final = "failed"
STALE: Final = "stale"
PARTIAL: Final = "partial"
NO_ACTIVE: Final = "no-active-release"

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


class _SourcePointers(RootModel[dict[str, int] | tuple[tuple[str, int], ...]]):
    pass


@final
class DataStatusError(ValueError):
    """Typed active-release predicate failure."""

    @override
    def __str__(self) -> str:
        return NO_ACTIVE


@dataclass(frozen=True, slots=True)
class ActiveData:
    """Component boundary pinned by the currently served release."""

    created_at: str
    catalog_id: int
    attribute_id: int
    materialization_id: int
    index_id: int
    relation_id: int
    source_ids: tuple[int, ...]


def data_statuses(database: Path) -> tuple[str, ...]:
    """Classify only candidates causally newer than the active release."""
    with connect_read_only(database) as connection:
        active = _active(connection)
        statuses: set[str] = set()
        _component_statuses(connection, active, statuses)
        _source_statuses(connection, active, statuses)
        _attribute_statuses(connection, active, statuses)
        _queue_statuses(connection, active, statuses)
    return tuple(item for item in (PENDING, FAILED, STALE, PARTIAL) if item in statuses)


def _active(connection: sqlite3.Connection) -> ActiveData:
    row = query(
        connection,
        """SELECT bundles.created_at,materializations.catalog_generation_id,
                  materializations.attribute_snapshot_id,bundles.materialization_id,
                  bundles.index_version_id,bundles.relation_snapshot_id,
                  catalogs.five_source_ids_json
           FROM active_release AS active
           JOIN release_bundles AS bundles ON bundles.id=active.bundle_id
           JOIN materialization_snapshots AS materializations
             ON materializations.id=bundles.materialization_id
           JOIN catalog_generations AS catalogs
             ON catalogs.id=materializations.catalog_generation_id
           WHERE active.singleton=1""",
    ).fetchone()
    if row is None:
        raise DataStatusError
    decoded = _SourcePointers.model_validate_json(as_text(row[6])).root
    source_ids = (
        tuple(decoded.values())
        if isinstance(decoded, dict)
        else tuple(item[1] for item in decoded)
    )
    return ActiveData(
        as_text(row[0]),
        as_int(row[1]),
        as_int(row[2]),
        as_int(row[3]),
        as_int(row[4]),
        as_int(row[5]),
        source_ids,
    )


def _component_statuses(
    connection: sqlite3.Connection,
    active: ActiveData,
    statuses: set[str],
) -> None:
    statements = (
        (
            """SELECT 'complete' FROM catalog_generations
               WHERE created_at>? AND id<>?""",
            active.catalog_id,
        ),
        (
            """SELECT status FROM materialization_snapshots
               WHERE created_at>? AND id<>?""",
            active.materialization_id,
        ),
        (
            "SELECT status FROM index_versions WHERE created_at>? AND id<>?",
            active.index_id,
        ),
        (
            "SELECT status FROM relation_snapshots WHERE created_at>? AND id<>?",
            active.relation_id,
        ),
        (
            "SELECT status FROM release_bundles WHERE created_at>? AND id<>?",
            0,
        ),
    )
    for statement, active_id in statements:
        rows = query(
            connection,
            statement,
            (active.created_at, active_id),
        ).fetchall()
        for row in rows:
            _record_status(as_text(row[0]), statuses)


def _source_statuses(
    connection: sqlite3.Connection,
    active: ActiveData,
    statuses: set[str],
) -> None:
    for source_id in active.source_ids:
        rows = query(
            connection,
            """SELECT candidates.status
               FROM source_snapshots AS served
               JOIN source_snapshots AS candidates
                 ON candidates.operation=served.operation
               WHERE served.id=? AND candidates.id<>served.id
                 AND (
                   candidates.parent_id=served.id
                   OR (
                     candidates.mode='full'
                     AND candidates.parent_id IS NULL
                     AND candidates.window_end>served.window_end
                   )
                 )""",
            (source_id,),
        ).fetchall()
        for row in rows:
            _record_status(as_text(row[0]), statuses)


def _attribute_statuses(
    connection: sqlite3.Connection,
    active: ActiveData,
    statuses: set[str],
) -> None:
    rows = query(
        connection,
        """SELECT status,complete_product_count,active_product_count
           FROM attribute_snapshots
           WHERE id<>? AND (
             parent_id=? OR catalog_generation_id IN (
               SELECT id FROM catalog_generations WHERE created_at>?
             )
           )""",
        (active.attribute_id, active.attribute_id, active.created_at),
    ).fetchall()
    for status, complete, total in rows:
        _record_status(as_text(status), statuses)
        if as_int(complete) != as_int(total):
            statuses.add(PARTIAL)


def _queue_statuses(
    connection: sqlite3.Connection,
    active: ActiveData,
    statuses: set[str],
) -> None:
    rows = query(
        connection,
        """SELECT queue.status
           FROM attribute_enrichment_queue AS queue
           JOIN catalog_generations AS catalogs
             ON catalogs.id=queue.catalog_generation_id
           WHERE catalogs.created_at>?""",
        (active.created_at,),
    ).fetchall()
    for row in rows:
        status = as_text(row[0])
        if status == "failed":
            statuses.add(FAILED)
        elif status not in {"complete", "completed"}:
            statuses.add(PENDING)
            statuses.add(PARTIAL)


def _record_status(status: str, statuses: set[str]) -> None:
    if status == "failed":
        statuses.add(FAILED)
    elif status == "building":
        statuses.add(PENDING)
    elif status in {"complete", "ready"}:
        statuses.add(STALE)
