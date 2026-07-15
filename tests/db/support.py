from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.materialization import MaterializationRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import (
    AttributeRecordInput,
    AttributeStateInput,
    RawBlobReceipt,
    RequestInput,
    SourceSnapshotInput,
    SyncPageInput,
    SyncRunInput,
    SyncWindowInput,
)
from g2b_compare.db.raw import RawBlobStore
from g2b_compare.db.repository import DatabaseRepository

if TYPE_CHECKING:
    from pathlib import Path

NOW = "2026-07-14T00:00:00Z"
OPS = ("contract-a", "contract-b", "contract-c", "registration", "delivery")


@dataclass(frozen=True, slots=True)
class TestDatabase:
    path: Path
    raw_root: Path
    source: DatabaseRepository
    ingest: IngestRepository
    attribute: AttributeRepository
    materialization: MaterializationRepository
    raw: RawBlobStore


def create_database(tmp_path: Path) -> TestDatabase:
    database = tmp_path / "todo3.sqlite3"
    raw_root = tmp_path / "raw"
    migrate(database)
    return TestDatabase(
        path=database,
        raw_root=raw_root,
        source=DatabaseRepository(database),
        ingest=IngestRepository(database),
        attribute=AttributeRepository(database),
        materialization=MaterializationRepository(database),
        raw=RawBlobStore(raw_root),
    )


def add_page(
    test_db: TestDatabase,
    operation: str,
    body: bytes,
    ordinal: int = 0,
) -> tuple[int, RawBlobReceipt]:
    receipt = test_db.raw.put(body, "application/json")
    test_db.ingest.register_raw_blob(receipt, NOW)
    run_id = test_db.ingest.create_run(
        SyncRunInput(operation=operation, mode="full", started_at=NOW)
    )
    window_id = test_db.ingest.create_window(
        SyncWindowInput(
            run_id=run_id,
            ordinal=ordinal,
            window_start="2026-07-01",
            window_end="2026-07-14",
        )
    )
    request_id = test_db.ingest.register_request(
        RequestInput(
            operation=operation,
            method="GET",
            official_path=f"/{operation}",
            params=(("pageNo", "1"),),
            created_at=NOW,
        )
    )
    page_id = test_db.ingest.create_page(
        SyncPageInput(
            run_id=run_id,
            window_id=window_id,
            page_no=1,
            request_manifest_id=request_id,
            body_sha=receipt.body_sha,
            item_count=1,
            total_count=1,
            status_code=200,
            content_type=receipt.content_type,
        )
    )
    return page_id, receipt


def add_catalog(test_db: TestDatabase) -> int:
    source_ids: list[tuple[str, int]] = []
    for operation in OPS:
        snapshot_id = test_db.source.create_source_snapshot(
            SourceSnapshotInput(
                operation=operation,
                parent_id=None,
                mode="full",
                window_start="2026-07-01",
                window_end="2026-07-14",
                completeness="complete",
            )
        )
        test_db.source.publish_source_snapshot(snapshot_id, NOW)
        source_ids.append((operation, snapshot_id))
    return test_db.source.create_catalog_generation(
        tuple(source_ids),
        NOW,
    )


def add_complete_attribute(
    test_db: TestDatabase,
    catalog_id: int,
    product_id: str = "P-1",
) -> tuple[int, int]:
    page_id, _receipt = add_page(test_db, "attributes", b'{"value":"8MP"}')
    snapshot_id = test_db.attribute.create_snapshot(catalog_id, None, 1)
    state = AttributeStateInput(
        product_id=product_id,
        fetch_status="complete-nonempty",
        source_fingerprint_sha="f" * 64,
        completed_at=NOW,
        origin_snapshot_id=None,
    )
    record = AttributeRecordInput(
        product_id=product_id,
        attribute_source_key="A-1",
        origin_page_id=page_id,
        raw_fields_json='{"value":"8MP"}',
        payload_sha="a" * 64,
    )
    test_db.attribute.replace_product(snapshot_id, state, (record,))
    test_db.attribute.publish_snapshot(snapshot_id, NOW)
    return snapshot_id, page_id
