"""Attribute successor lifecycle transactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import attribute_state
from .connection import connect
from .models import AttributeStateInput
from .repository import RepositoryContractError
from .sql import ResultCursor, as_int, as_text, query

if TYPE_CHECKING:
    from pathlib import Path

    from .models import AttributeRecordInput


@dataclass(frozen=True, slots=True)
class AttributeRepository:
    """Transaction boundary for attribute snapshots."""

    database: Path

    def create_snapshot(
        self,
        catalog_generation_id: int,
        parent_id: int | None,
        active_product_count: int,
    ) -> int:
        """Create an unpublished attribute successor."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                """INSERT INTO attribute_snapshots(
                    catalog_generation_id, parent_id, complete_product_count,
                    active_product_count, status
                ) VALUES (?, ?, 0, ?, 'building')""",
                (catalog_generation_id, parent_id, active_product_count),
            )
            return _row_id(cursor)

    def record_product_fingerprint(
        self, catalog_generation_id: int, product_id: str, sha: str
    ) -> None:
        """Record the canonical fingerprint for one catalog product."""
        with connect(self.database) as connection:
            attribute_state.record_fingerprint(
                connection,
                attribute_state.Fingerprint(catalog_generation_id, product_id, sha),
            )

    def replace_product(
        self,
        snapshot_id: int,
        state: AttributeStateInput,
        records: tuple[AttributeRecordInput, ...],
    ) -> None:
        """Atomically replace one product's attributes and state."""
        if state.fetch_status not in ("complete-nonempty", "complete-empty"):
            raise RepositoryContractError(detail="complete state required for replace")
        if state.fetch_status == "complete-nonempty" and not records:
            raise RepositoryContractError(detail="nonempty state requires records")
        if state.fetch_status == "complete-empty" and records:
            raise RepositoryContractError(detail="empty state forbids records")
        if any(record.product_id != state.product_id for record in records):
            raise RepositoryContractError(
                detail="attribute record product identity must match state"
            )
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            _ = query(
                connection,
                """DELETE FROM attribute_records
                WHERE attribute_snapshot_id = ? AND product_id = ?""",
                (snapshot_id, state.product_id),
            )
            for record in records:
                _ = query(
                    connection,
                    """INSERT INTO attribute_records(
                        attribute_snapshot_id, product_id, attribute_source_key,
                        origin_page_id, raw_fields_json, payload_sha
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        record.product_id,
                        record.attribute_source_key,
                        record.origin_page_id,
                        record.raw_fields_json,
                        record.payload_sha,
                    ),
                )
            attribute_state.upsert_state(connection, snapshot_id, state)
            _ = query(connection, "COMMIT")

    def carry_forward_product(
        self,
        parent_snapshot_id: int,
        successor_snapshot_id: int,
        product_id: str,
    ) -> None:
        """Copy recent complete rows while retaining their origin pages."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            state = query(
                connection,
                """SELECT fetch_status, source_fingerprint_sha, completed_at
                FROM attribute_product_states
                WHERE attribute_snapshot_id = ? AND product_id = ?""",
                (parent_snapshot_id, product_id),
            ).fetchone()
            if state is None or state[0] not in (
                "complete-nonempty",
                "complete-empty",
                "carried-forward",
            ):
                raise RepositoryContractError(detail="attribute origin is not complete")
            prior_fingerprint = as_text(state[1])
            successor_catalog_id = attribute_state.catalog_id(
                connection, successor_snapshot_id
            )
            current_fingerprint = attribute_state.fingerprint(
                connection, successor_catalog_id, product_id
            )
            if current_fingerprint is None:
                current_fingerprint = prior_fingerprint
                attribute_state.record_fingerprint(
                    connection,
                    attribute_state.Fingerprint(
                        successor_catalog_id, product_id, prior_fingerprint
                    ),
                )
            if current_fingerprint != prior_fingerprint:
                attribute_state.upsert_state(
                    connection,
                    successor_snapshot_id,
                    AttributeStateInput(
                        product_id,
                        "pending",
                        current_fingerprint,
                        None,
                        parent_snapshot_id,
                    ),
                )
                attribute_state.enqueue(connection, successor_catalog_id, product_id)
                _ = query(connection, "COMMIT")
                return
            _ = query(
                connection,
                """INSERT INTO attribute_records(
                    attribute_snapshot_id, product_id, attribute_source_key,
                    origin_page_id, raw_fields_json, payload_sha
                )
                SELECT ?, product_id, attribute_source_key,
                       origin_page_id, raw_fields_json, payload_sha
                FROM attribute_records
                WHERE attribute_snapshot_id = ? AND product_id = ?""",
                (successor_snapshot_id, parent_snapshot_id, product_id),
            )
            attribute_state.upsert_state(
                connection,
                successor_snapshot_id,
                AttributeStateInput(
                    product_id=product_id,
                    fetch_status="carried-forward",
                    source_fingerprint_sha=as_text(state[1]),
                    completed_at=None if state[2] is None else as_text(state[2]),
                    origin_snapshot_id=parent_snapshot_id,
                ),
            )
            attribute_state.clear_queue(connection, successor_catalog_id, product_id)
            _ = query(connection, "COMMIT")

    def set_state(self, snapshot_id: int, state: AttributeStateInput) -> None:
        """Set one pending or failed state without replacing retained rows."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            attribute_state.upsert_state(connection, snapshot_id, state)
            if state.fetch_status in ("pending", "failed"):
                state_catalog_id = attribute_state.catalog_id(connection, snapshot_id)
                attribute_state.record_fingerprint(
                    connection,
                    attribute_state.Fingerprint(
                        state_catalog_id,
                        state.product_id,
                        state.source_fingerprint_sha,
                    ),
                )
                attribute_state.enqueue(connection, state_catalog_id, state.product_id)
            _ = query(connection, "COMMIT")

    def publish_snapshot(self, snapshot_id: int, published_at: str) -> None:
        """Validate complete product coverage and atomically swap the pointer."""
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            snapshot = query(
                connection,
                """SELECT catalog_generation_id, active_product_count, status
                FROM attribute_snapshots WHERE id = ?""",
                (snapshot_id,),
            ).fetchone()
            if snapshot is None or snapshot[2] != "building":
                raise RepositoryContractError(
                    detail="attribute snapshot not publishable"
                )
            state_rows = query(
                connection,
                """SELECT fetch_status, COUNT(*)
                FROM attribute_product_states
                WHERE attribute_snapshot_id = ? GROUP BY fetch_status""",
                (snapshot_id,),
            ).fetchall()
            state_count = sum(as_int(row[1]) for row in state_rows)
            if state_count != as_int(snapshot[1]):
                raise RepositoryContractError(detail="attribute product state missing")
            complete = sum(
                as_int(row[1])
                for row in state_rows
                if row[0] in ("complete-nonempty", "complete-empty", "carried-forward")
            )
            _ = query(
                connection,
                """UPDATE attribute_snapshots
                SET status = 'complete', complete_product_count = ?, published_at = ?
                WHERE id = ?""",
                (complete, published_at, snapshot_id),
            )
            _ = query(
                connection,
                """INSERT INTO active_attribute_snapshots(
                    catalog_generation_id, snapshot_id
                ) VALUES (?, ?)
                ON CONFLICT(catalog_generation_id)
                DO UPDATE SET snapshot_id = excluded.snapshot_id""",
                (as_int(snapshot[0]), snapshot_id),
            )
            _ = query(connection, "COMMIT")

    def coverage(self, snapshot_id: int) -> tuple[int, int]:
        """Return covered and active product counts for one snapshot."""
        with connect(self.database) as connection:
            row = query(
                connection,
                """SELECT complete_product_count, active_product_count
                FROM attribute_snapshots WHERE id = ?""",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise RepositoryContractError(detail="attribute snapshot missing")
        return as_int(row[0]), as_int(row[1])


def _row_id(cursor: ResultCursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RepositoryContractError(detail="SQLite did not return a row id")
    return row_id
