"""Concrete live adapter for persisted attribute synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import singledispatch
from typing import TYPE_CHECKING, Final

import httpx

from g2b_compare.contracts.live_output import LiveObservedDocument
from g2b_compare.contracts.quota import Operation, effective_ceiling
from g2b_compare.contracts.wire import HttpxRequester
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.models import AttributeRecordInput
from g2b_compare.db.sql import as_int, query
from g2b_compare.observability.logging import configure_logging, operation_log
from g2b_compare.sources.thing_list import (
    AttributeCollection,
    AttributeEvidenceStore,
    AttributePage,
    AttributeRequest,
    CompleteAttributeCollection,
    IncompleteAttributeCollection,
    ThingListAdapter,
    assemble_pages,
)
from g2b_compare.sync.attribute_queue import (
    AttributeQueueStore,
    CompleteFetch,
    FailedFetch,
    FetchCommit,
    apply_fetch,
)
from g2b_compare.sync.attribute_quota import AttributeQuotaGate
from g2b_compare.sync.catalog import advance_catalog

if TYPE_CHECKING:
    from pathlib import Path

PAGE_SIZE: Final = 100


@dataclass(frozen=True, slots=True)
class _AttributeClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def provider_window_start(self, now: datetime) -> datetime:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)


@singledispatch
def _outcome(
    collection: AttributeCollection,
    observed_at: str,
) -> CompleteFetch | FailedFetch:
    _ = (collection, observed_at)
    raise TypeError


def _complete(
    collection: CompleteAttributeCollection,
    observed_at: str,
) -> CompleteFetch:
    return CompleteFetch(
        tuple(
            AttributeRecordInput(
                record.product_id,
                record.source_key,
                record.origin_page_id,
                record.raw_fields_json,
                record.payload_sha,
            )
            for record in collection.records
        ),
        observed_at,
        collection.official_no_data,
    )


def _incomplete(
    collection: IncompleteAttributeCollection,
    observed_at: str,
) -> FailedFetch:
    _ = observed_at
    return FailedFetch(collection.reason)


_ = _outcome.register(CompleteAttributeCollection)(_complete)
_ = _outcome.register(IncompleteAttributeCollection)(_incomplete)


def run_attribute_sync(
    database: Path,
    contract: Path,
    raw_root: Path,
    service_key: str,
) -> int:
    """Drain the persisted attribute queue through the verified live adapter."""
    document = LiveObservedDocument.model_validate_json(contract.read_bytes())
    manifest = next(
        item.manifest
        for item in document.manifests
        if item.operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
    )
    observed_at = datetime.now(UTC)
    advance = advance_catalog(database, observed_at.isoformat())
    entries = AttributeQueueStore(database).ready(
        advance.catalog_generation_id,
        observed_at,
        effective_ceiling(manifest.quota),
    )
    repository = AttributeRepository(database)
    applied = 0
    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10),
    ) as client:
        adapter = ThingListAdapter(
            manifest,
            HttpxRequester(client),
            service_key,
            AttributeQuotaGate(
                IngestRepository(database),
                manifest,
                _AttributeClock(),
            ),
            AttributeEvidenceStore(database, raw_root),
        )
        for entry in entries:
            operation_log(
                configure_logging(),
                operation="attributes",
                status="product-started",
            )
            pages: list[AttributePage] = []
            page_no = 1
            while True:
                page = adapter.fetch_page(
                    AttributeRequest(
                        advance.catalog_generation_id,
                        entry.product_id,
                        page_no,
                        PAGE_SIZE,
                    )
                )
                pages.append(page)
                operation_log(
                    configure_logging(),
                    operation="attributes",
                    status="page-persisted",
                    context={
                        "run": advance.catalog_generation_id,
                        "page": page_no,
                    },
                )
                if page_no * page.page_size >= page.total_count:
                    break
                page_no += 1
            result = apply_fetch(
                repository,
                FetchCommit(
                    advance.catalog_generation_id,
                    advance.catalog_generation_id,
                    advance.attribute_snapshot_id,
                    entry.product_id,
                    entry.source_fingerprint_sha,
                    _outcome(assemble_pages(tuple(pages)), observed_at.isoformat()),
                ),
            )
            applied += int(result == "applied")
            operation_log(
                configure_logging(),
                operation="attributes",
                status=result,
                context={"run": advance.catalog_generation_id},
            )
    return applied


def attribute_pending_count(database: Path) -> int:
    """Count unfinished products in the latest active attribute candidate."""
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT COUNT(*)
               FROM attribute_product_states AS states
               JOIN attribute_snapshots AS snapshots
                 ON snapshots.id=states.attribute_snapshot_id
               WHERE snapshots.id=(SELECT MAX(id) FROM attribute_snapshots)
                 AND states.fetch_status IN ('pending','failed')""",
        ).fetchone()
    return 0 if row is None else as_int(row[0])
