"""Atomic repositories for source snapshots and catalog generations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override

from .connection import connect
from .hashes import catalog_source_identity
from .sql import ResultCursor, as_int, as_text, query

if TYPE_CHECKING:
    from pathlib import Path

    from .models import SourceRecordInput, SourceSnapshotInput

SOURCE_OPERATION_COUNT: Final = 5


@final
class RepositoryContractError(Exception):
    """A requested persistence transition violates a database contract."""

    detail: str
    operation: str | None
    resume_not_before: str | None

    def __init__(
        self,
        detail: str,
        operation: str | None = None,
        resume_not_before: str | None = None,
    ) -> None:
        """Initialize one rejected transition receipt."""
        super().__init__(detail)
        self.detail = detail
        self.operation = operation
        self.resume_not_before = resume_not_before

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class DatabaseRepository:
    """Transaction boundary for source and catalog state."""

    database: Path

    def create_source_snapshot(self, source: SourceSnapshotInput) -> int:
        """Create a building snapshot without changing its active pointer."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                """
                INSERT INTO source_snapshots(
                    operation, parent_id, mode, window_start, window_end,
                    completeness, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'building')
                """,
                (
                    source.operation,
                    source.parent_id,
                    source.mode,
                    source.window_start,
                    source.window_end,
                    source.completeness,
                ),
            )
            return _row_id(cursor)

    def add_source_record(
        self,
        snapshot_id: int,
        operation: str,
        record: SourceRecordInput,
    ) -> None:
        """Insert one staging row while preserving its original page."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """
                INSERT INTO source_records(
                    source_snapshot_id, operation, source_record_key, product_id,
                    origin_page_id, raw_fields_json, payload_sha,
                    canonical_record_sha, is_tombstone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    operation,
                    record.source_record_key,
                    record.product_id,
                    record.origin_page_id,
                    record.raw_fields_json,
                    record.payload_sha,
                    record.canonical_record_sha,
                    int(record.is_tombstone),
                ),
            )

    def publish_source_snapshot(self, snapshot_id: int, published_at: str) -> None:
        """Complete a source snapshot and swap its pointer in one transaction."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            row = query(
                connection,
                "SELECT operation, status FROM source_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None or row[1] != "building":
                raise RepositoryContractError(
                    detail=f"source snapshot {snapshot_id} is not publishable"
                )
            operation = as_text(row[0])
            _ = query(
                connection,
                """
                UPDATE source_snapshots
                SET status = 'complete', published_at = ?
                WHERE id = ?
                """,
                (published_at, snapshot_id),
            )
            _ = query(
                connection,
                """
                INSERT INTO active_source_snapshots(operation, snapshot_id)
                VALUES (?, ?)
                ON CONFLICT(operation) DO UPDATE SET snapshot_id = excluded.snapshot_id
                """,
                (operation, snapshot_id),
            )
            _ = query(connection, "COMMIT")

    def active_source_record_keys(self, operation: str) -> tuple[str, ...]:
        """Read only rows reachable through the operation's active pointer."""
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                SELECT records.source_record_key
                FROM active_source_snapshots AS active
                JOIN source_records AS records
                  ON records.source_snapshot_id = active.snapshot_id
                 AND records.operation = active.operation
                WHERE active.operation = ? AND records.is_tombstone = 0
                ORDER BY records.source_record_key
                """,
                (operation,),
            ).fetchall()
        return tuple(as_text(row[0]) for row in rows)

    def create_catalog_generation(
        self,
        source_ids: tuple[tuple[str, int], ...],
        created_at: str,
    ) -> int:
        """Create or replay one exact five-source catalog generation."""
        operation_count = len({item[0] for item in source_ids})
        if len(source_ids) != SOURCE_OPERATION_COUNT or (
            operation_count != SOURCE_OPERATION_COUNT
        ):
            raise RepositoryContractError(detail="catalog requires five operations")
        source_json, source_sha = catalog_source_identity(source_ids)
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            active_rows = query(
                connection,
                """
                SELECT active.operation, active.snapshot_id
                FROM active_source_snapshots AS active
                JOIN source_snapshots AS snapshots
                  ON snapshots.id = active.snapshot_id
                 AND snapshots.operation = active.operation
                WHERE snapshots.status = 'complete'
                  AND snapshots.completeness = 'complete'
                """,
            ).fetchall()
            active_sources = frozenset(
                (as_text(row[0]), as_int(row[1])) for row in active_rows
            )
            if active_sources != frozenset(source_ids):
                raise RepositoryContractError(
                    detail="catalog sources must equal the complete active source set"
                )
            _ = query(
                connection,
                """
                INSERT INTO catalog_generations(
                    catalog_source_sha, five_source_ids_json, created_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(catalog_source_sha) DO NOTHING
                """,
                (source_sha, source_json, created_at),
            )
            row = query(
                connection,
                """
                SELECT id, five_source_ids_json FROM catalog_generations
                WHERE catalog_source_sha = ?
                """,
                (source_sha,),
            ).fetchone()
            if row is None or row[1] != source_json:
                raise RepositoryContractError(
                    detail="catalog digest collision detected"
                )
            catalog_id = as_int(row[0])
            _ = query(connection, "COMMIT")
            return catalog_id


def _row_id(cursor: ResultCursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RepositoryContractError(detail="SQLite did not return a row id")
    return row_id
