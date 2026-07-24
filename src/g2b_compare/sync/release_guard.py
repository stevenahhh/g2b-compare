"""Deterministic read-only freeze of the complete active release graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, assert_never, override

from pydantic import TypeAdapter

from g2b_compare.db.connection import connect
from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.db.sql import SqlRow, SqlValue, as_int, as_text, query

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

type JsonObject = dict[str, JsonValue]

SOURCE_MAP_ADAPTER: Final = TypeAdapter(dict[str, int])
MISSING_RELEASE_GRAPH: Final = "active-release-graph-missing"
SOURCE_OPERATION_COUNT: Final = 5


@dataclass(frozen=True, slots=True)
class ReleaseFreezeError(Exception):
    """An active release points to an incomplete referenced graph."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def frozen_active_release(database: Path) -> bytes:
    """Serialize pointer, components, cache payloads, and source manifest."""
    with connect(database) as connection:
        pointer = query(
            connection,
            "SELECT singleton, bundle_id FROM active_release",
        ).fetchone()
        if pointer is None:
            return canonical_json({"active_release": None}).encode()
        bundle_id = as_int(pointer[1])
        bundle = _required(
            connection,
            "SELECT * FROM release_bundles WHERE id = ?",
            (bundle_id,),
        )
        materialization_id = as_int(bundle[1])
        index_id = as_int(bundle[2])
        relation_id = as_int(bundle[3])
        attempt_no = as_int(bundle[10])
        materialization = _required(
            connection,
            "SELECT * FROM materialization_snapshots WHERE id = ?",
            (materialization_id,),
        )
        catalog_id = as_int(materialization[1])
        attribute_id = as_int(materialization[2])
        index = _required(
            connection,
            "SELECT * FROM index_versions WHERE id = ?",
            (index_id,),
        )
        relation = _required(
            connection,
            "SELECT * FROM relation_snapshots WHERE id = ?",
            (relation_id,),
        )
        attribute = _required(
            connection,
            "SELECT * FROM attribute_snapshots WHERE id = ?",
            (attribute_id,),
        )
        catalog = _required(
            connection,
            "SELECT * FROM catalog_generations WHERE id = ?",
            (catalog_id,),
        )
        source_map = SOURCE_MAP_ADAPTER.validate_json(as_text(catalog[2]))
        source_ids = tuple(source_map[key] for key in sorted(source_map))
        if len(source_ids) != SOURCE_OPERATION_COUNT:
            raise ReleaseFreezeError(MISSING_RELEASE_GRAPH)
        sources = query(
            connection,
            """SELECT * FROM source_snapshots
               WHERE id IN (?, ?, ?, ?, ?) ORDER BY operation, id""",
            source_ids,
        ).fetchall()
        cache = query(
            connection,
            """SELECT * FROM comparator_cache
               WHERE release_bundle_id = ? AND attempt_no = ?
               ORDER BY anchor_id, slot""",
            (bundle_id, attempt_no),
        ).fetchall()
    document: JsonObject = {
        "active_release": {
            "pointer": _named(("singleton", "bundle_id"), pointer),
            "release_bundle": _named(_BUNDLE_COLUMNS, bundle),
            "materialization": _named(_MATERIALIZATION_COLUMNS, materialization),
            "index": _named(_INDEX_COLUMNS, index),
            "relation": _named(_RELATION_COLUMNS, relation),
            "attribute": _named(_ATTRIBUTE_COLUMNS, attribute),
            "source_manifest": {
                "catalog": _named(_CATALOG_COLUMNS, catalog),
                "source_snapshots": [_named(_SOURCE_COLUMNS, row) for row in sources],
            },
            "comparator_cache": [_named(_CACHE_COLUMNS, row) for row in cache],
        }
    }
    return canonical_json(document).encode()


def _required(
    connection: sqlite3.Connection,
    statement: str,
    parameters: tuple[SqlValue, ...],
) -> SqlRow:
    row = query(connection, statement, parameters).fetchone()
    if row is None:
        raise ReleaseFreezeError(MISSING_RELEASE_GRAPH)
    return row


def _named(columns: tuple[str, ...], row: SqlRow) -> JsonObject:
    if len(columns) != len(row):
        raise ReleaseFreezeError(MISSING_RELEASE_GRAPH)
    return {name: _cell(value) for name, value in zip(columns, row, strict=True)}


def _cell(value: SqlValue) -> JsonValue:
    match value:
        case str() | int() | None:
            return value
        case float():
            return repr(value)
        case bytes():
            return value.hex()
        case _:
            assert_never(value)


_BUNDLE_COLUMNS: Final = (
    "id",
    "materialization_id",
    "index_version_id",
    "relation_snapshot_id",
    "ranking_version",
    "expected_cache_rows",
    "written_cache_rows",
    "cache_content_sha",
    "release_bundle_sha",
    "status",
    "attempt_no",
    "ready_attempt_no",
    "heartbeat_at",
    "created_at",
    "slot_policy_version",
)
_MATERIALIZATION_COLUMNS: Final = (
    "id",
    "catalog_generation_id",
    "attribute_snapshot_id",
    "materialization_source_sha",
    "normalization_version",
    "materialization_policy_version",
    "status",
    "attempt_no",
    "heartbeat_at",
    "created_at",
)
_INDEX_COLUMNS: Final = (
    "id",
    "materialization_id",
    "index_artifact_sha",
    "index_manifest_sha",
    "status",
    "created_at",
)
_RELATION_COLUMNS: Final = (
    "id",
    "source_manifest_sha",
    "relation_content_sha",
    "status",
    "created_at",
)
_ATTRIBUTE_COLUMNS: Final = (
    "id",
    "catalog_generation_id",
    "parent_id",
    "complete_product_count",
    "active_product_count",
    "status",
    "published_at",
)
_CATALOG_COLUMNS: Final = (
    "id",
    "catalog_source_sha",
    "five_source_ids_json",
    "created_at",
)
_SOURCE_COLUMNS: Final = (
    "id",
    "operation",
    "parent_id",
    "mode",
    "window_start",
    "window_end",
    "completeness",
    "status",
    "published_at",
)
_CACHE_COLUMNS: Final = (
    "release_bundle_id",
    "attempt_no",
    "anchor_id",
    "slot",
    "payload_json",
    "payload_sha",
)
