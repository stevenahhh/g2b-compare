from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.models import AttributeRecordInput, AttributeStateInput
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_int, query

from .support import (
    NOW,
    add_catalog,
    add_complete_attribute,
    add_page,
    create_database,
)
from .support import (
    TestDatabase as DatabaseFixture,
)

if TYPE_CHECKING:
    from pathlib import Path


def create_ready_bundle(
    test_db: DatabaseFixture,
    statuses: tuple[str, str, str],
    index_materialization_id: int | None = None,
) -> tuple[int, int]:
    catalog_id = add_catalog(test_db)
    attribute_id, _page_id = add_complete_attribute(test_db, catalog_id)
    materialization_id = test_db.materialization.create(
        catalog_id, attribute_id, ("n1", "p1")
    )
    index_owner = (
        materialization_id
        if index_materialization_id is None
        else index_materialization_id
    )
    with connect(test_db.path) as connection:
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = ? WHERE id = ?",
            (statuses[0], materialization_id),
        )
        index_id = query(
            connection,
            """
            INSERT INTO index_versions VALUES (
                NULL, ?, 'artifact', 'manifest', ?, ?
            )
            """,
            (index_owner, statuses[1], NOW),
        ).lastrowid
        relation_id = query(
            connection,
            """
            INSERT INTO relation_snapshots VALUES (
                NULL, 'source', 'content', ?, ?
            )
            """,
            (statuses[2], NOW),
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
    return materialization_id, bundle_id


def test_replace_product_rejects_record_for_different_product(tmp_path: Path) -> None:
    # Given: one building snapshot and a state for P-1
    test_db = create_database(tmp_path)
    catalog_id = add_catalog(test_db)
    snapshot_id = test_db.attribute.create_snapshot(catalog_id, None, 1)
    page_id, _receipt = add_page(test_db, "attributes", b"{}")
    state = AttributeStateInput("P-1", "complete-nonempty", "f" * 64, NOW, None)
    wrong_record = AttributeRecordInput("P-2", "A-1", page_id, "{}", "a" * 64)

    # When: the repository receives a record owned by another product
    with pytest.raises(RepositoryContractError, match="product identity"):
        test_db.attribute.replace_product(snapshot_id, state, (wrong_record,))

    # Then: neither product state nor record is persisted
    with connect(test_db.path) as connection:
        state_count = query(
            connection,
            """
            SELECT COUNT(*) FROM attribute_product_states
            WHERE attribute_snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        record_count = query(
            connection,
            "SELECT COUNT(*) FROM attribute_records WHERE attribute_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    assert state_count is not None
    assert record_count is not None
    assert (as_int(state_count[0]), as_int(record_count[0])) == (0, 0)


def test_attribute_record_requires_matching_product_state(tmp_path: Path) -> None:
    # Given: a complete snapshot containing only P-1
    test_db = create_database(tmp_path)
    catalog_id = add_catalog(test_db)
    snapshot_id, page_id = add_complete_attribute(test_db, catalog_id)

    # When: hostile SQL inserts a record for P-2 without a matching state
    with (
        connect(test_db.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"),
    ):
        _ = query(
            connection,
            """
            INSERT INTO attribute_records VALUES (?, 'P-2', 'A-2', ?, '{}', ?)
            """,
            (snapshot_id, page_id, "b" * 64),
        )


@pytest.mark.parametrize(
    "statuses",
    [
        ("building", "complete", "complete"),
        ("complete", "building", "complete"),
        ("complete", "complete", "building"),
    ],
)
def test_active_release_rejects_incomplete_component(
    tmp_path: Path,
    statuses: tuple[str, str, str],
) -> None:
    # Given: a ready bundle containing one incomplete component
    test_db = create_database(tmp_path)
    _materialization_id, bundle_id = create_ready_bundle(test_db, statuses)

    # When: hostile SQL attempts to publish the bundle
    with (
        connect(test_db.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="ready"),
    ):
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )


def test_active_release_rejects_index_for_other_materialization(
    tmp_path: Path,
) -> None:
    # Given: a ready bundle whose index belongs to a different materialization
    test_db = create_database(tmp_path)
    catalog_id = add_catalog(test_db)
    attribute_id, _page_id = add_complete_attribute(test_db, catalog_id)
    other_materialization_id = test_db.materialization.create(
        catalog_id, attribute_id, ("n2", "p2")
    )
    with connect(test_db.path) as connection:
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = 'complete' WHERE id = ?",
            (other_materialization_id,),
        )
    _materialization_id, bundle_id = create_ready_bundle(
        test_db,
        ("complete", "complete", "complete"),
        other_materialization_id,
    )

    # When: hostile SQL attempts to publish the identity-inconsistent bundle
    with (
        connect(test_db.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="ready"),
    ):
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )


def test_active_release_rejects_materialization_attribute_catalog_mismatch(
    tmp_path: Path,
) -> None:
    # Given: a ready bundle whose materialization and attribute use different catalogs
    test_db = create_database(tmp_path)
    materialization_id, bundle_id = create_ready_bundle(
        test_db, ("complete", "complete", "complete")
    )
    other_catalog_id = add_catalog(test_db)
    with connect(test_db.path) as connection:
        _ = query(
            connection,
            """
            UPDATE materialization_snapshots SET catalog_generation_id = ?
            WHERE id = ?
            """,
            (other_catalog_id, materialization_id),
        )

    # When: hostile SQL attempts to publish the identity-inconsistent bundle
    with (
        connect(test_db.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="ready"),
    ):
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )


def test_active_release_accepts_complete_consistent_components(tmp_path: Path) -> None:
    # Given: a ready bundle with complete, identity-consistent components
    test_db = create_database(tmp_path)
    materialization_id, bundle_id = create_ready_bundle(
        test_db, ("complete", "complete", "complete")
    )

    # When: the bundle is published
    with connect(test_db.path) as connection:
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )
        row = query(connection, "SELECT id FROM active_materialization").fetchone()

    # Then: the intended materialization is visible
    assert row is not None
    assert as_int(row[0]) == materialization_id
