from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_text, query
from g2b_compare.materialize.products import merge_products
from g2b_compare.materialize.repository import (
    CandidateRows,
    MaterializationValidationError,
    publish_candidate,
)
from tests.db.support import add_catalog, add_complete_attribute, create_database

from .support import offer

if TYPE_CHECKING:
    from pathlib import Path


def _candidate(tmp_path: Path) -> tuple[Path, int]:
    database = create_database(tmp_path)
    catalog_id = add_catalog(database)
    attribute_id, _page_id = add_complete_attribute(database, catalog_id)
    materialization_id = database.materialization.create(
        catalog_id,
        attribute_id,
        ("normalization-v1", "policy-v1"),
    )
    return database.path, materialization_id


def test_complete_candidate_never_changes_active_release(tmp_path: Path) -> None:
    # Given
    database, materialization_id = _candidate(tmp_path)

    # When
    publish_candidate(database, materialization_id, CandidateRows((), (), ()))

    # Then
    with connect(database) as connection:
        status = query(
            connection,
            "SELECT status FROM materialization_snapshots WHERE id = ?",
            (materialization_id,),
        ).fetchone()
        active = query(connection, "SELECT bundle_id FROM active_release").fetchall()
    assert status is not None
    assert as_text(status[0]) == "complete"
    assert active == []


def test_failed_candidate_marks_only_candidate_failed(tmp_path: Path) -> None:
    # Given
    database, materialization_id = _candidate(tmp_path)
    invalid = CandidateRows((), (), ("missing-product",))

    # When
    with pytest.raises(
        MaterializationValidationError, match="candidate coverage invalid"
    ):
        publish_candidate(database, materialization_id, invalid)

    # Then
    with connect(database) as connection:
        status = query(
            connection,
            "SELECT status FROM materialization_snapshots WHERE id = ?",
            (materialization_id,),
        ).fetchone()
        active = query(connection, "SELECT bundle_id FROM active_release").fetchall()
    assert status is not None
    assert as_text(status[0]) == "failed"
    assert active == []


def test_database_insert_failure_rolls_back_rows_and_marks_candidate_failed(
    tmp_path: Path,
) -> None:
    # Given
    database, materialization_id = _candidate(tmp_path)
    product = merge_products(
        (
            offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "DUP"),
            offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "DUP"),
        ),
        (),
    )[0]

    # When
    with pytest.raises(sqlite3.IntegrityError):
        publish_candidate(
            database,
            materialization_id,
            CandidateRows((product,), (), ()),
        )

    # Then
    with connect(database) as connection:
        status = query(
            connection,
            "SELECT status FROM materialization_snapshots WHERE id = ?",
            (materialization_id,),
        ).fetchone()
        product_count = query(connection, "SELECT COUNT(*) FROM products").fetchone()
    assert status is not None
    assert as_text(status[0]) == "failed"
    assert product_count == (0,)
