"""Atomic attribute replacement and queue completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db import attribute_state
from g2b_compare.db.connection import connect
from g2b_compare.db.models import AttributeStateInput
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import query

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.sync.attribute_queue_state import CompleteFetch, FetchCommit


def publish_complete_fetch(
    database: Path,
    commit: FetchCommit,
    outcome: CompleteFetch,
) -> None:
    """Replace rows, complete state, and clear retry queue in one transaction."""
    records = outcome.records
    if not records and not outcome.official_no_data:
        raise RepositoryContractError(detail="complete-empty requires official no-data")
    if any(record.product_id != commit.product_id for record in records):
        raise RepositoryContractError(detail="attribute product identity mismatch")
    status = "complete-nonempty" if records else "complete-empty"
    with connect(database) as connection:
        _ = query(connection, "BEGIN IMMEDIATE")
        catalog_id = attribute_state.catalog_id(connection, commit.snapshot_id)
        if catalog_id != commit.expected_generation_id:
            raise RepositoryContractError(
                detail="attribute snapshot generation mismatch"
            )
        _ = query(
            connection,
            """DELETE FROM attribute_records
            WHERE attribute_snapshot_id = ? AND product_id = ?""",
            (commit.snapshot_id, commit.product_id),
        )
        for record in records:
            _ = query(
                connection,
                """INSERT INTO attribute_records(
                    attribute_snapshot_id, product_id, attribute_source_key,
                    origin_page_id, raw_fields_json, payload_sha
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    commit.snapshot_id,
                    record.product_id,
                    record.attribute_source_key,
                    record.origin_page_id,
                    record.raw_fields_json,
                    record.payload_sha,
                ),
            )
        attribute_state.upsert_state(
            connection,
            commit.snapshot_id,
            AttributeStateInput(
                commit.product_id,
                status,
                commit.source_fingerprint_sha,
                outcome.completed_at,
                None,
            ),
        )
        attribute_state.clear_queue(connection, catalog_id, commit.product_id)
        _ = query(connection, "COMMIT")
