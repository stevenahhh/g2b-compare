from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query

from . import support
from .test_invariant_repairs import create_ready_bundle

if TYPE_CHECKING:
    from pathlib import Path

type StatusComponent = Literal["materialization", "index", "relation", "attribute"]
type IdentityMutation = Literal[
    "materialization_catalog", "materialization_attribute", "index_owner"
]
type ArtifactMutation = Literal[
    "materialization_source", "index_artifact", "relation_content"
]
type CacheMutation = Literal["insert", "update", "delete"]


@dataclass(frozen=True, slots=True)
class ActiveRelease:
    database: support.TestDatabase
    bundle_id: int
    materialization_id: int
    attribute_id: int
    index_id: int
    relation_id: int


def _create_active_release(tmp_path: Path, cached: bool = False) -> ActiveRelease:
    test_db = support.create_database(tmp_path)
    materialization_id, bundle_id = create_ready_bundle(
        test_db, ("complete", "complete", "complete")
    )
    with connect(test_db.path) as connection:
        row = query(
            connection,
            """
            SELECT materialization_snapshots.attribute_snapshot_id,
                   release_bundles.index_version_id,
                   release_bundles.relation_snapshot_id
            FROM release_bundles
            JOIN materialization_snapshots
              ON materialization_snapshots.id = release_bundles.materialization_id
            WHERE release_bundles.id = ?
            """,
            (bundle_id,),
        ).fetchone()
        assert row is not None
        if cached:
            _ = query(
                connection,
                """
                UPDATE release_bundles
                SET expected_cache_rows = 1, written_cache_rows = 1
                WHERE id = ?
                """,
                (bundle_id,),
            )
            _ = query(
                connection,
                "INSERT INTO comparator_cache VALUES (?, 1, 'A', 1, '{}', 'payload')",
                (bundle_id,),
            )
        _ = query(
            connection,
            "INSERT INTO active_release VALUES (1, ?)",
            (bundle_id,),
        )
    return ActiveRelease(
        database=test_db,
        bundle_id=bundle_id,
        materialization_id=materialization_id,
        attribute_id=as_int(row[0]),
        index_id=as_int(row[1]),
        relation_id=as_int(row[2]),
    )


def _assert_active(release: ActiveRelease) -> None:
    with connect(release.database.path) as connection:
        pointer = query(connection, "SELECT bundle_id FROM active_release").fetchone()
        visible = query(connection, "SELECT id FROM active_materialization").fetchone()
    assert pointer == (release.bundle_id,)
    assert visible == (release.materialization_id,)


@pytest.mark.parametrize(
    "component",
    ["materialization", "index", "relation", "attribute"],
)
def test_active_release_rejects_component_status_downgrade(
    tmp_path: Path,
    component: StatusComponent,
) -> None:
    # Given: a complete active release
    release = _create_active_release(tmp_path)
    match component:
        case "materialization":
            statement = (
                "UPDATE materialization_snapshots SET status = 'building' WHERE id = ?"
            )
            component_id = release.materialization_id
        case "index":
            statement = "UPDATE index_versions SET status = 'building' WHERE id = ?"
            component_id = release.index_id
        case "relation":
            statement = "UPDATE relation_snapshots SET status = 'building' WHERE id = ?"
            component_id = release.relation_id
        case "attribute":
            statement = (
                "UPDATE attribute_snapshots SET status = 'building' WHERE id = ?"
            )
            component_id = release.attribute_id
        case _:
            assert_never(component)

    # When: hostile SQL downgrades one active dependency
    with (
        connect(release.database.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="active release"),
    ):
        _ = query(connection, statement, (component_id,))

    # Then: the active pointer and visible materialization remain intact
    _assert_active(release)


@pytest.mark.parametrize(
    "mutation",
    ["materialization_catalog", "materialization_attribute", "index_owner"],
)
def test_active_release_rejects_component_ownership_change(
    tmp_path: Path,
    mutation: IdentityMutation,
) -> None:
    # Given: a complete active release and another valid ownership target
    release = _create_active_release(tmp_path)
    with connect(release.database.path) as connection:
        catalog_row = query(
            connection,
            "SELECT catalog_generation_id FROM materialization_snapshots WHERE id = ?",
            (release.materialization_id,),
        ).fetchone()
    assert catalog_row is not None
    catalog_id = as_int(catalog_row[0])
    match mutation:
        case "materialization_catalog":
            target_id = support.add_catalog(release.database)
            statement = (
                "UPDATE materialization_snapshots SET catalog_generation_id = ? "
                "WHERE id = ?"
            )
            owner_id = release.materialization_id
        case "materialization_attribute":
            target_id, _page_id = support.add_complete_attribute(
                release.database, catalog_id, "P-2"
            )
            statement = (
                "UPDATE materialization_snapshots SET attribute_snapshot_id = ? "
                "WHERE id = ?"
            )
            owner_id = release.materialization_id
        case "index_owner":
            target_id = release.database.materialization.create(
                catalog_id, release.attribute_id, ("n2", "p2")
            )
            with connect(release.database.path) as connection:
                _ = query(
                    connection,
                    """
                    UPDATE materialization_snapshots SET status = 'complete'
                    WHERE id = ?
                    """,
                    (target_id,),
                )
            statement = "UPDATE index_versions SET materialization_id = ? WHERE id = ?"
            owner_id = release.index_id
        case _:
            assert_never(mutation)

    # When: hostile SQL reassigns an active component identity
    with (
        connect(release.database.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="active release"),
    ):
        _ = query(connection, statement, (target_id, owner_id))

    # Then: the active pointer and visible materialization remain intact
    _assert_active(release)


@pytest.mark.parametrize(
    "mutation",
    ["materialization_source", "index_artifact", "relation_content"],
)
def test_active_release_rejects_component_artifact_identity_change(
    tmp_path: Path,
    mutation: ArtifactMutation,
) -> None:
    # Given: a complete active release
    release = _create_active_release(tmp_path)
    match mutation:
        case "materialization_source":
            statement = (
                "UPDATE materialization_snapshots "
                "SET materialization_source_sha = 'changed' WHERE id = ?"
            )
            component_id = release.materialization_id
        case "index_artifact":
            statement = (
                "UPDATE index_versions SET index_artifact_sha = 'changed' WHERE id = ?"
            )
            component_id = release.index_id
        case "relation_content":
            statement = (
                "UPDATE relation_snapshots SET relation_content_sha = 'changed' "
                "WHERE id = ?"
            )
            component_id = release.relation_id
        case _:
            assert_never(mutation)

    # When: hostile SQL changes a pinned artifact identity
    with (
        connect(release.database.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="active release"),
    ):
        _ = query(connection, statement, (component_id,))

    # Then: the active pointer and visible materialization remain intact
    _assert_active(release)


def test_active_release_rejects_bundle_downgrade(tmp_path: Path) -> None:
    # Given: a complete active release
    release = _create_active_release(tmp_path)

    # When: hostile SQL downgrades the active bundle
    with (
        connect(release.database.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="active release"),
    ):
        _ = query(
            connection,
            "UPDATE release_bundles SET status = 'building' WHERE id = ?",
            (release.bundle_id,),
        )

    # Then: the active pointer and visible materialization remain intact
    _assert_active(release)


@pytest.mark.parametrize("mutation", ["insert", "update", "delete"])
def test_active_release_rejects_cache_mutation(
    tmp_path: Path,
    mutation: CacheMutation,
) -> None:
    # Given: an active release with one complete cache row
    release = _create_active_release(tmp_path, cached=True)
    match mutation:
        case "insert":
            statement = (
                "INSERT INTO comparator_cache VALUES (?, 1, 'B', 1, '{}', 'other')"
            )
        case "update":
            statement = (
                "UPDATE comparator_cache SET payload_sha = 'changed' "
                "WHERE release_bundle_id = ?"
            )
        case "delete":
            statement = "DELETE FROM comparator_cache WHERE release_bundle_id = ?"
        case _:
            assert_never(mutation)

    # When: hostile SQL changes the pinned cache attempt
    with (
        connect(release.database.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="active release"),
    ):
        _ = query(connection, statement, (release.bundle_id,))

    # Then: the active pointer and visible materialization remain intact
    _assert_active(release)
