from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import AttributeRecordInput
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sources.thing_list import (
    AttributeAdapterError,
    AttributeRequest,
)
from g2b_compare.sync.attribute_queue import (
    AttributeQueueStore,
    CatalogAttributeInput,
    CompleteFetch,
    FetchCommit,
    PreviousAttribute,
    QueueEntry,
    QueuePlanningInput,
    apply_fetch,
    plan_attribute_queue,
)
from g2b_compare.sync.attribute_quota import AttributeQuotaError
from tests.db.support import NOW, add_catalog, add_complete_attribute, create_database
from tests.sources.test_thing_list import (
    RequesterStub,
    ResponseStub,
    attribute_body,
)
from tests.sync.attribute_review_support import (
    LEDGER_INSERT,
    LedgerRequester,
    make_adapter,
)

NOW_DT = datetime(2026, 7, 16, tzinfo=UTC)


def test_review_quota_reservation_is_bound_to_http_dispatch(tmp_path: Path) -> None:
    database = tmp_path / "quota.sqlite3"
    migrate(database)
    attempted_at = NOW_DT.isoformat()
    with connect(database) as connection:
        _ = connection.executemany(
            LEDGER_INSERT,
            (
                (Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE, attempted_at, "2026-07-16")
                for _index in range(9999)
            ),
        )
    response = ResponseStub(200, attribute_body())
    requester = LedgerRequester(database, response)
    adapter = make_adapter(database, tmp_path / "raw", requester, NOW_DT)

    _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
    with pytest.raises(AttributeQuotaError, match="quota-ceiling"):
        _ = adapter.fetch_page(AttributeRequest(2, "22065235", 1, 10))
    assert requester.dispatch_counts == [10_000]

    resumed_at = NOW_DT + timedelta(hours=24, microseconds=1)
    resumed = LedgerRequester(database, response)
    resumed_adapter = make_adapter(database, tmp_path / "raw", resumed, resumed_at)
    _ = resumed_adapter.fetch_page(AttributeRequest(2, "22065235", 1, 10))
    cutoff = (resumed_at - timedelta(hours=24) + timedelta(microseconds=1)).isoformat()
    assert resumed.dispatch_counts == [10_001]
    assert (
        IngestRepository(database).quota_usage(
            Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE, cutoff
        )
        == 1
    )


def test_review_complete_fetch_atomically_clears_ready_queue(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog = add_catalog(db)
    parent, _page = add_complete_attribute(db, catalog)
    successor = db.attribute.create_snapshot(catalog, parent, 1)
    db.attribute.carry_forward_product(parent, successor, "P-1")
    AttributeQueueStore(db.path).seed(
        catalog, (QueueEntry(catalog, "P-1", 0, "f" * 64, "new"),)
    )
    commit = FetchCommit(
        catalog,
        catalog,
        successor,
        "P-1",
        "f" * 64,
        CompleteFetch((), NOW, official_no_data=True),
    )

    assert apply_fetch(AttributeRepository(db.path), commit) == "applied"
    with connect(db.path) as connection:
        state = query(
            connection,
            """SELECT fetch_status FROM attribute_product_states
            WHERE attribute_snapshot_id = ? AND product_id = ?""",
            (successor, "P-1"),
        ).fetchone()
    assert state is not None
    assert as_text(state[0]) == "complete-empty"
    assert AttributeQueueStore(db.path).ready(catalog, NOW_DT, 1) == ()


def test_review_response_page_metadata_is_not_replaced_by_request(
    tmp_path: Path,
) -> None:
    valid = attribute_body()
    missing = valid.replace(b', "numOfRows": 10', b"", 1)
    wrong_count = valid.replace(b'"totalCount": 1', b'"totalCount": 2', 1)
    wrong_page = valid.replace(b'"pageNo": 1', b'"pageNo": 2', 1)
    duplicate = valid.replace(b'"pageNo": 1', b'"pageNo": 1, "pageNo": 1', 1)
    payloads = (
        duplicate,
        missing,
        wrong_count,
        wrong_page,
    )

    outcomes: list[str] = []
    for index, payload in enumerate(payloads):
        requester = RequesterStub(ResponseStub(200, payload))
        adapter = make_adapter(
            tmp_path / str(index) / "metadata.sqlite3",
            tmp_path / str(index) / "raw",
            requester,
            NOW_DT,
        )
        try:
            _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
        except AttributeAdapterError as error:
            outcomes.append(error.reason)
        else:
            outcomes.append("accepted")
    assert outcomes == [
        "page-metadata-invalid",
        "page-metadata-invalid",
        "page-item-count-mismatch",
        "page-metadata-mismatch",
    ]


def test_review_carry_forward_is_persisted_with_origin(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog = add_catalog(db)
    parent, origin_page_id = add_complete_attribute(db, catalog)
    successor = db.attribute.create_snapshot(catalog, parent, 1)
    plan = plan_attribute_queue(
        QueuePlanningInput(
            catalog,
            (CatalogAttributeInput("P-1", 0, "f" * 64),),
            (
                PreviousAttribute(
                    product_id="P-1",
                    source_fingerprint_sha="f" * 64,
                    completed_at=NOW_DT - timedelta(days=1),
                    complete=True,
                    origin_snapshot_id=parent,
                ),
            ),
            NOW_DT,
        )
    )

    AttributeQueueStore(db.path).persist_plan(db.attribute, successor, plan)
    with connect(db.path) as connection:
        row = query(
            connection,
            """SELECT states.fetch_status, states.origin_snapshot_id,
                      records.origin_page_id
            FROM attribute_product_states AS states
            JOIN attribute_records AS records
              ON records.attribute_snapshot_id = states.attribute_snapshot_id
             AND records.product_id = states.product_id
            WHERE states.attribute_snapshot_id = ? AND states.product_id = ?""",
            (successor, "P-1"),
        ).fetchone()
    assert row is not None
    assert (as_text(row[0]), as_int(row[1]), as_int(row[2])) == (
        "carried-forward",
        parent,
        origin_page_id,
    )


def test_review_stale_response_has_resumable_raw_page_evidence(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog = add_catalog(db)
    parent, old_page_id = add_complete_attribute(db, catalog)
    successor = db.attribute.create_snapshot(catalog, parent, 1)
    db.attribute.carry_forward_product(parent, successor, "P-1")
    response = ResponseStub(200, attribute_body(product_id="P-1"))
    requester = RequesterStub(response)
    adapter = make_adapter(db.path, db.raw_root, requester, NOW_DT)

    page = adapter.fetch_page(AttributeRequest(catalog, "P-1", 1, 10))
    current_catalog = add_catalog(db)
    fetched = page.records[0]
    commit = FetchCommit(
        catalog,
        current_catalog,
        successor,
        "P-1",
        "f" * 64,
        CompleteFetch(
            (
                AttributeRecordInput(
                    "P-1",
                    fetched.source_key,
                    fetched.origin_page_id,
                    fetched.raw_fields_json,
                    fetched.payload_sha,
                ),
            ),
            NOW,
        ),
    )
    assert apply_fetch(db.attribute, commit) == "raw-only"

    restarted_requester = RequesterStub(response)
    restarted = make_adapter(db.path, db.raw_root, restarted_requester, NOW_DT)
    replay = restarted.fetch_page(AttributeRequest(catalog, "P-1", 1, 10))
    with connect(db.path) as connection:
        overlay = query(
            connection,
            """SELECT origin_page_id, raw_fields_json FROM attribute_records
            WHERE attribute_snapshot_id = ? AND product_id = ?""",
            (successor, "P-1"),
        ).fetchone()
        staged = query(
            connection,
            """SELECT COUNT(*) FROM sync_pages AS pages
            JOIN sync_runs AS runs ON runs.id = pages.run_id
            WHERE runs.mode = ?""",
            (f"attribute:{catalog}:P-1:10",),
        ).fetchone()
    assert overlay is not None
    assert (as_int(overlay[0]), as_text(overlay[1])) == (
        old_page_id,
        '{"value":"8MP"}',
    )
    assert staged is not None
    assert as_int(staged[0]) == 1
    assert replay.records[0].origin_page_id == page.records[0].origin_page_id
    assert restarted_requester.calls == []
