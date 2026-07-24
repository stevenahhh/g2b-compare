from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.models import (
    AttributeRecordInput,
    AttributeStateInput,
    RequestInput,
    SourceSnapshotInput,
)
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_int, as_text, query

from .support import NOW, OPS, add_catalog, add_complete_attribute, create_database

if TYPE_CHECKING:
    from pathlib import Path


def test_failed_attribute_fetch_rejects_partial_rows_and_retains_prior(
    tmp_path: Path,
) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    parent_id, origin_page_id = add_complete_attribute(db, catalog_id)
    successor_id = db.attribute.create_snapshot(catalog_id, parent_id, 1)
    db.attribute.carry_forward_product(parent_id, successor_id, "P-1")
    failed = AttributeStateInput("P-1", "failed", "f" * 64, None, parent_id)
    partial = AttributeRecordInput("P-1", "PARTIAL-NEW", origin_page_id, "{}", "b" * 64)

    with pytest.raises(RepositoryContractError, match="complete"):
        db.attribute.replace_product(successor_id, failed, (partial,))

    with connect(db.path) as connection:
        rows = query(
            connection,
            """
            SELECT attribute_source_key FROM attribute_records
            WHERE attribute_snapshot_id = ? ORDER BY attribute_source_key
            """,
            (successor_id,),
        ).fetchall()
    assert tuple(as_text(row[0]) for row in rows) == ("A-1",)


def test_catalog_rejects_fabricated_source_snapshot_ids(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    fabricated = tuple((operation, index + 9000) for index, operation in enumerate(OPS))

    with pytest.raises(RepositoryContractError, match="active"):
        _ = db.source.create_catalog_generation(fabricated, NOW)


def test_catalog_rejects_nonactive_source_snapshot_id(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    _ = add_catalog(db)
    inactive_id = db.source.create_source_snapshot(
        SourceSnapshotInput(
            operation="delivery",
            parent_id=None,
            mode="full",
            window_start="2026-07-01",
            window_end="2026-07-14",
            completeness="complete",
        )
    )
    with connect(db.path) as connection:
        rows = query(
            connection,
            "SELECT operation, snapshot_id FROM active_source_snapshots",
        ).fetchall()
    supplied = tuple(
        (as_text(row[0]), inactive_id if row[0] == "delivery" else as_int(row[1]))
        for row in rows
    )

    with pytest.raises(RepositoryContractError, match="active"):
        _ = db.source.create_catalog_generation(supplied, NOW)


@pytest.mark.parametrize("parameter", ["apiServiceKey", "auth", "totallyUnknown"])
def test_request_manifest_rejects_secret_shaped_and_unknown_parameters(
    tmp_path: Path,
    parameter: str,
) -> None:
    db = create_database(tmp_path)
    request = RequestInput("op", "GET", "/op", ((parameter, "dummy"),), NOW)

    with pytest.raises(RepositoryContractError, match="allowlisted"):
        _ = db.ingest.register_request(request)

    with connect(db.path) as connection:
        row = query(connection, "SELECT COUNT(*) FROM request_manifests").fetchone()
    assert row is not None
    assert as_int(row[0]) == 0


def test_building_partial_release_cannot_become_active(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    attribute_id, _page_id = add_complete_attribute(db, catalog_id)
    materialization_id = db.materialization.create(
        catalog_id, attribute_id, ("n1", "p1")
    )
    with connect(db.path) as connection:
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = 'complete' WHERE id = ?",
            (materialization_id,),
        )
        index_id = query(
            connection,
            """
            INSERT INTO index_versions VALUES (
                NULL, ?, 'artifact', 'manifest', 'complete', ?
            )
            """,
            (materialization_id, NOW),
        ).lastrowid
        relation_id = query(
            connection,
            """
            INSERT INTO relation_snapshots VALUES (
                NULL, 'source', 'content', 'complete', ?
            )
            """,
            (NOW,),
        ).lastrowid
        assert index_id is not None
        assert relation_id is not None
        bundle_id = query(
            connection,
            """
            INSERT INTO release_bundles (
                id, materialization_id, index_version_id, relation_snapshot_id,
                ranking_version, expected_cache_rows, written_cache_rows,
                cache_content_sha, release_bundle_sha, status, attempt_no,
                ready_attempt_no, heartbeat_at, created_at
            ) VALUES (
                NULL, ?, ?, ?, 'r1', 3, 1, NULL, NULL,
                'building', 1, NULL, ?, ?
            )
            """,
            (materialization_id, index_id, relation_id, NOW, NOW),
        ).lastrowid
        assert bundle_id is not None
        with pytest.raises(sqlite3.IntegrityError, match="ready"):
            _ = query(
                connection,
                "INSERT INTO active_release VALUES (1, ?)",
                (bundle_id,),
            )
        visible = query(
            connection, "SELECT COUNT(*) FROM active_materialization"
        ).fetchone()
    assert visible is not None
    assert as_int(visible[0]) == 0


def test_interrupted_raw_write_retries_with_stale_temp_present(
    tmp_path: Path,
) -> None:
    db = create_database(tmp_path)
    staged = db.raw.stage(b"same-body", "application/json")

    receipt = db.raw.put(b"same-body", "application/json")

    assert receipt.path.is_file()
    assert not staged.temporary_path.exists()
