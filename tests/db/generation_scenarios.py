from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.hashes import canonical_record_sha
from g2b_compare.db.sql import as_int, as_text, query

from .source_scenarios import canonical_record, snapshot_input
from .support import (
    NOW,
    TestDatabase,
    add_catalog,
    add_complete_attribute,
    create_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def scenario_relevant_content_change(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    assert canonical_record_sha(canonical_record()) != canonical_record_sha(
        canonical_record("400만화소")
    )
    catalog_id = add_catalog(db)
    parent_id, _page_id = add_complete_attribute(db, catalog_id)
    successor_catalog = _advance_catalog(db, "contract-a")
    successor_id = db.attribute.create_snapshot(successor_catalog, parent_id, 1)
    db.attribute.record_product_fingerprint(successor_catalog, "P-1", "g" * 64)
    db.attribute.carry_forward_product(parent_id, successor_id, "P-1")
    with connect(db.path) as connection:
        state = query(
            connection,
            """
            SELECT fetch_status FROM attribute_product_states
            WHERE attribute_snapshot_id = ? AND product_id = 'P-1'
            """,
            (successor_id,),
        ).fetchone()
        rows = query(
            connection,
            """
            SELECT COUNT(*) FROM attribute_records
            WHERE attribute_snapshot_id = ? AND product_id = 'P-1'
            """,
            (successor_id,),
        ).fetchone()
        queued = query(
            connection,
            """
            SELECT COUNT(*) FROM attribute_enrichment_queue
            WHERE catalog_generation_id = ? AND product_id = 'P-1'
            """,
            (successor_catalog,),
        ).fetchone()
    assert state is not None
    assert as_text(state[0]) == "pending"
    assert rows is not None
    assert as_int(rows[0]) == 0
    assert queued is not None
    assert as_int(queued[0]) == 1


def scenario_price_only_no_requeue(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    assert canonical_record_sha(canonical_record()) == canonical_record_sha(
        canonical_record()
    )
    catalog_id = add_catalog(db)
    parent_id, origin_page_id = add_complete_attribute(db, catalog_id)
    successor_catalog = _advance_catalog(db, "delivery")
    successor_id = db.attribute.create_snapshot(successor_catalog, parent_id, 1)
    db.attribute.record_product_fingerprint(successor_catalog, "P-1", "f" * 64)
    db.attribute.carry_forward_product(parent_id, successor_id, "P-1")
    db.attribute.publish_snapshot(successor_id, NOW)
    with connect(db.path) as connection:
        state = query(
            connection,
            """
            SELECT fetch_status, origin_snapshot_id
            FROM attribute_product_states
            WHERE attribute_snapshot_id = ? AND product_id = 'P-1'
            """,
            (successor_id,),
        ).fetchone()
        record = query(
            connection,
            """
            SELECT origin_page_id FROM attribute_records
            WHERE attribute_snapshot_id = ? AND product_id = 'P-1'
            """,
            (successor_id,),
        ).fetchone()
        fingerprint = query(
            connection,
            """
            SELECT fingerprint_sha FROM product_source_fingerprints
            WHERE catalog_generation_id = ? AND product_id = 'P-1'
            """,
            (successor_catalog,),
        ).fetchone()
        queued = query(
            connection,
            """
            SELECT COUNT(*) FROM attribute_enrichment_queue
            WHERE catalog_generation_id = ? AND product_id = 'P-1'
            """,
            (successor_catalog,),
        ).fetchone()
    assert state is not None
    assert (as_text(state[0]), as_int(state[1])) == ("carried-forward", parent_id)
    assert record is not None
    assert as_int(record[0]) == origin_page_id
    assert fingerprint is not None
    assert as_text(fingerprint[0]) == "f" * 64
    assert queued is not None
    assert as_int(queued[0]) == 0


def _advance_catalog(db: TestDatabase, operation: str) -> int:
    with connect(db.path) as connection:
        parent_row = query(
            connection,
            "SELECT snapshot_id FROM active_source_snapshots WHERE operation = ?",
            (operation,),
        ).fetchone()
    assert parent_row is not None
    snapshot_id = db.source.create_source_snapshot(
        snapshot_input(operation, as_int(parent_row[0]))
    )
    db.source.publish_source_snapshot(snapshot_id, NOW)
    with connect(db.path) as connection:
        rows = query(
            connection,
            """
            SELECT operation, snapshot_id FROM active_source_snapshots
            ORDER BY operation
            """,
        ).fetchall()
    return db.source.create_catalog_generation(
        tuple((as_text(row[0]), as_int(row[1])) for row in rows), NOW
    )
