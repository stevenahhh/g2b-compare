from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.hashes import materialization_source_sha
from g2b_compare.db.models import AttributeStateInput
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_int, query

from .support import NOW, add_catalog, add_complete_attribute, create_database

if TYPE_CHECKING:
    from pathlib import Path


def empty_state(product_id: str = "P-1") -> AttributeStateInput:
    return AttributeStateInput(
        product_id=product_id,
        fetch_status="complete-empty",
        source_fingerprint_sha="f" * 64,
        completed_at=NOW,
        origin_snapshot_id=None,
    )


def scenario_attribute_origin_missing(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    successor = db.attribute.create_snapshot(catalog_id, None, 1)
    with pytest.raises(RepositoryContractError, match="origin"):
        db.attribute.carry_forward_product(999, successor, "P-1")


def scenario_attribute_state_missing(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot = db.attribute.create_snapshot(add_catalog(db), None, 1)
    with pytest.raises(RepositoryContractError, match="state missing"):
        db.attribute.publish_snapshot(snapshot, NOW)


def scenario_attribute_state_transition(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot = db.attribute.create_snapshot(add_catalog(db), None, 1)
    invalid = AttributeStateInput("P-1", "invalid", "f" * 64, None, None)
    with pytest.raises(sqlite3.IntegrityError):
        db.attribute.set_state(snapshot, invalid)


def scenario_attribute_deleted_upstream(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot = db.attribute.create_snapshot(add_catalog(db), None, 0)
    db.attribute.publish_snapshot(snapshot, NOW)
    assert db.attribute.coverage(snapshot) == (0, 0)


def scenario_attribute_complete_empty(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot = db.attribute.create_snapshot(add_catalog(db), None, 1)
    db.attribute.replace_product(snapshot, empty_state(), ())
    db.attribute.publish_snapshot(snapshot, NOW)
    assert db.attribute.coverage(snapshot) == (1, 1)


def scenario_attribute_partial_retains_old(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    parent, _page_id = add_complete_attribute(db, catalog_id)
    successor = db.attribute.create_snapshot(catalog_id, parent, 1)
    db.attribute.carry_forward_product(parent, successor, "P-1")
    db.attribute.set_state(
        successor,
        AttributeStateInput("P-1", "failed", "f" * 64, None, parent),
    )
    db.attribute.publish_snapshot(successor, NOW)
    with connect(db.path) as connection:
        row = query(
            connection,
            """
            SELECT COUNT(*) FROM attribute_records
            WHERE attribute_snapshot_id = ? AND product_id = 'P-1'
            """,
            (successor,),
        ).fetchone()
    assert row is not None
    assert as_int(row[0]) == 1
    assert db.attribute.coverage(successor) == (0, 1)


def scenario_attribute_coverage_count(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot = db.attribute.create_snapshot(add_catalog(db), None, 2)
    db.attribute.replace_product(snapshot, empty_state("P-1"), ())
    db.attribute.set_state(
        snapshot,
        AttributeStateInput("P-2", "pending", "g" * 64, None, None),
    )
    db.attribute.publish_snapshot(snapshot, NOW)
    assert db.attribute.coverage(snapshot) == (1, 2)


def scenario_materialization_digest_collision(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    attribute_id, _page_id = add_complete_attribute(db, catalog_id)
    digest = materialization_source_sha(catalog_id, (1, 2, 3, 5, 4), attribute_id)
    other_catalog = add_catalog(db)
    other_attribute = db.attribute.create_snapshot(other_catalog, None, 0)
    db.attribute.publish_snapshot(other_attribute, NOW)
    with connect(db.path) as connection:
        _ = query(
            connection,
            """
            INSERT INTO materialization_snapshots VALUES (
                NULL, ?, ?, ?, 'n1', 'p1', 'building', 1, ?, ?
            )
            """,
            (other_catalog, other_attribute, digest, NOW, NOW),
        )
    with pytest.raises(RepositoryContractError, match="collision"):
        _ = db.materialization.create(catalog_id, attribute_id, ("n1", "p1"))


def scenario_happy_lifecycle(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    materialization_ids: list[int] = []
    parent: int | None = None
    for index in range(3):
        snapshot = db.attribute.create_snapshot(catalog_id, parent, 1)
        db.attribute.replace_product(snapshot, empty_state(), ())
        db.attribute.publish_snapshot(snapshot, f"2026-07-14T00:00:0{index}Z")
        materialization_ids.append(
            db.materialization.create(catalog_id, snapshot, ("n1", "p1"))
        )
        parent = snapshot
    assert len(set(materialization_ids)) == 3
    assert parent is not None
    assert (
        db.materialization.create(catalog_id, parent, ("n1", "p1"))
        == (materialization_ids[-1])
    )
