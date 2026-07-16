from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import (
    AttributeRecordInput,
    AttributeStateInput,
    RequestInput,
    SourceRecordInput,
    SyncPageInput,
    SyncRunInput,
    SyncWindowInput,
)
from g2b_compare.db.raw import RawBlobStore
from g2b_compare.db.sql import as_text, query
from g2b_compare.sync.paginator import (
    PageMeta,
    PageScope,
    PageSequence,
    ValidatedPageSet,
)
from g2b_compare.sync.publisher import (
    PublicationRequest,
    SourceDelta,
    publish_operation,
)
from g2b_compare.sync.release_guard import frozen_active_release

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.sync.catalog import CatalogAdvance

NOW = "2026-07-16T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class FixtureDatabase:
    path: Path
    ingest: IngestRepository
    attribute: AttributeRepository
    raw: RawBlobStore


def database(path: Path) -> FixtureDatabase:
    migrate(path)
    return FixtureDatabase(
        path,
        IngestRepository(path),
        AttributeRepository(path),
        RawBlobStore(path.parent / f"{path.stem}-raw"),
    )


def add_page(db: FixtureDatabase, operation: str, marker: str) -> int:
    body = f'{{"operation":"{operation}","marker":"{marker}"}}'.encode()
    receipt = db.raw.put(body, "application/json")
    db.ingest.register_raw_blob(receipt, NOW)
    run_id = db.ingest.create_run(SyncRunInput(operation, "full", NOW))
    window_id = db.ingest.create_window(
        SyncWindowInput(run_id, 0, "2026-07-15", "2026-07-15")
    )
    request_id = db.ingest.register_request(
        RequestInput(
            operation,
            "GET",
            f"/{operation}",
            (("pageNo", "1"),),
            NOW,
        )
    )
    return db.ingest.create_page(
        SyncPageInput(
            run_id,
            window_id,
            1,
            request_id,
            receipt.body_sha,
            1,
            1,
            200,
            receipt.content_type,
        )
    )


def record(
    key: str,
    product_id: str,
    origin_page_id: int,
    marker: str,
) -> SourceRecordInput:
    sha = (marker * 64)[:64]
    return SourceRecordInput(
        key,
        product_id,
        origin_page_id,
        f'{{"marker":"{marker}"}}',
        sha,
        sha,
    )


def publish(
    db: FixtureDatabase,
    operation: Operation,
    mode: str,
    records: tuple[SourceDelta, ...],
) -> int:
    assert mode in ("full", "delta")
    return publish_operation(
        db.path,
        PublicationRequest(
            operation,
            mode,
            "2026-07-15",
            "2026-07-15",
            NOW,
            records,
            validated_pages(
                operation,
                "2026-07-15",
                "2026-07-15",
                len(records),
            ),
        ),
    )


def validated_pages(
    operation: Operation,
    window_start: str,
    window_end: str,
    item_count: int,
) -> tuple[ValidatedPageSet, ...]:
    scope = PageScope(operation.value, window_start, window_end)
    sequence = PageSequence.empty(scope).add(PageMeta(1, 100, item_count, item_count))
    return (sequence.finalize(),)


def setup_five_sources(db: FixtureDatabase) -> None:
    for index, operation in enumerate(tuple(Operation)[:5]):
        rows: tuple[SourceDelta, ...] = ()
        if index == 0:
            page_id = add_page(db, operation.value, f"source-{index}")
            rows = (SourceDelta(record("K-1", "P-1", page_id, "a")),)
        if operation is Operation.GET_DELIVERY_REQUEST_DETAIL:
            page_id = add_page(db, operation.value, "delivery")
            rows = (SourceDelta(record("D-1", "P-1", page_id, "d")),)
        _ = publish(db, operation, "full", rows)


def complete_products(
    db: FixtureDatabase,
    advance: CatalogAdvance,
    product_ids: tuple[str, ...],
) -> int:
    snapshot_id = db.attribute.create_snapshot(
        advance.catalog_generation_id,
        advance.attribute_snapshot_id,
        len(product_ids),
    )
    for index, product_id in enumerate(product_ids):
        page_id = add_page(db, "attributes", f"attribute-{index}")
        fingerprint = _fingerprint(db, advance.catalog_generation_id, product_id)
        db.attribute.replace_product(
            snapshot_id,
            AttributeStateInput(
                product_id,
                "complete-nonempty",
                fingerprint,
                NOW,
                None,
            ),
            (
                AttributeRecordInput(
                    product_id,
                    f"A-{index}",
                    page_id,
                    f'{{"product":"{product_id}"}}',
                    (str(index) * 64)[:64],
                ),
            ),
        )
    db.attribute.publish_snapshot(snapshot_id, NOW)
    return snapshot_id


def _fingerprint(db: FixtureDatabase, catalog_id: int, product_id: str) -> str:
    with connect(db.path) as connection:
        row = query(
            connection,
            """SELECT fingerprint_sha FROM product_source_fingerprints
               WHERE catalog_generation_id = ? AND product_id = ?""",
            (catalog_id, product_id),
        ).fetchone()
    assert row is not None
    return as_text(row[0])


def release_bytes(db: FixtureDatabase) -> bytes:
    return frozen_active_release(db.path)
