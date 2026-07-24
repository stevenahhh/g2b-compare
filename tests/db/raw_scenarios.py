from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.models import RawBlobReceipt, RequestInput
from g2b_compare.db.prune import RawRetentionRepository
from g2b_compare.db.raw import RawBlobIntegrityError
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_text, query

from .source_scenarios import snapshot_input, source_record
from .support import NOW, add_catalog, add_complete_attribute, add_page, create_database

if TYPE_CHECKING:
    from pathlib import Path


def scenario_kill_before_rename(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    staged = db.raw.stage(b"body", "application/json")
    assert staged.temporary_path.is_file()
    assert not staged.receipt.path.exists()
    staged.temporary_path.unlink()


def scenario_raw_sha_mismatch(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    receipt = db.raw.put(b"body", "application/json")
    wrong = RawBlobReceipt(
        body_sha="0" * 64,
        path=receipt.path,
        content_type=receipt.content_type,
        byte_count=receipt.byte_count,
    )
    with pytest.raises(RawBlobIntegrityError):
        db.raw.verify(wrong)


def scenario_corrupt_gzip(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    receipt = db.raw.put(b"body", "application/json")
    _ = receipt.path.write_bytes(b"not-gzip")
    with pytest.raises(RawBlobIntegrityError):
        db.raw.verify(receipt)


def scenario_text_plain_raw(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    receipt = db.raw.put(b"provider error", "text/plain")
    db.ingest.register_raw_blob(receipt, NOW)
    with connect(db.path) as connection:
        row = query(
            connection,
            "SELECT content_type FROM raw_blobs WHERE body_sha = ?",
            (receipt.body_sha,),
        ).fetchone()
    assert row is not None
    assert as_text(row[0]) == "text/plain"


def scenario_request_manifest_key_leak(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    request = RequestInput(
        operation="op",
        method="GET",
        official_path="/op",
        params=(("serviceKey", "secret"),),
        created_at=NOW,
    )
    with pytest.raises(RepositoryContractError, match="secret parameter"):
        _ = db.ingest.register_request(request)


def scenario_prune_active_raw(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    page_id, receipt = add_page(db, "contract-a", b"source")
    snapshot_id = db.source.create_source_snapshot(snapshot_input("contract-a"))
    db.source.add_source_record(snapshot_id, "contract-a", source_record(page_id))
    db.source.publish_source_snapshot(snapshot_id, NOW)
    protected = RawRetentionRepository(db.path).protected_body_shas()
    assert receipt.body_sha in protected


def scenario_prune_active_attribute_origin(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    _attribute_id, page_id = add_complete_attribute(db, catalog_id)
    with connect(db.path) as connection:
        row = query(
            connection,
            "SELECT body_sha FROM sync_pages WHERE id = ?",
            (page_id,),
        ).fetchone()
    assert row is not None
    protected = RawRetentionRepository(db.path).protected_body_shas()
    assert as_text(row[0]) in protected


def scenario_prune_materialization_origin(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    attribute_id, page_id = add_complete_attribute(db, catalog_id)
    materialization_id = db.materialization.create(
        catalog_id, attribute_id, ("n1", "p1")
    )
    with connect(db.path) as connection:
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = 'complete' WHERE id = ?",
            (materialization_id,),
        )
        _ = query(connection, "DELETE FROM active_attribute_snapshots")
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
                NULL, ?, ?, ?, 'r1', 0, 0, 'cache', 'bundle',
                'ready', 1, 1, ?, ?
            )
            """,
            (materialization_id, index_id, relation_id, NOW, NOW),
        ).lastrowid
        assert bundle_id is not None
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )
        row = query(
            connection,
            "SELECT body_sha FROM sync_pages WHERE id = ?",
            (page_id,),
        ).fetchone()
    assert row is not None
    protected = RawRetentionRepository(db.path).protected_body_shas()
    assert as_text(row[0]) in protected
