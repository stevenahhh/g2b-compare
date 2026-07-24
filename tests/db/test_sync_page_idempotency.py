from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.models import (
    RequestInput,
    SyncPageInput,
    SyncRunInput,
    SyncWindowInput,
)
from g2b_compare.db.sql import as_text, query

from .support import NOW, create_database
from .support import TestDatabase as DatabaseFixture

if TYPE_CHECKING:
    from pathlib import Path

OPERATION = "getMASCntrctPrdctInfoList"


def _prepare(test_db: DatabaseFixture) -> tuple[int, int, int]:
    run_id = test_db.ingest.create_run(
        SyncRunInput(operation=OPERATION, mode="full", started_at=NOW)
    )
    window_id = test_db.ingest.create_window(
        SyncWindowInput(
            run_id=run_id,
            ordinal=0,
            window_start="2024-12-14",
            window_end="2025-01-13",
        )
    )
    request_id = test_db.ingest.register_request(
        RequestInput(
            operation=OPERATION,
            method="GET",
            official_path=f"/{OPERATION}",
            params=(("pageNo", "16"),),
            created_at=NOW,
        )
    )
    return run_id, window_id, request_id


def test_create_page_retry_with_identical_content_is_idempotent(
    tmp_path: Path,
) -> None:
    """A retried page insert with the same content must not raise or duplicate."""
    test_db = create_database(tmp_path)
    run_id, window_id, request_id = _prepare(test_db)
    receipt = test_db.raw.put(b'{"page":16}', "application/json")
    test_db.ingest.register_raw_blob(receipt, NOW)
    page = SyncPageInput(
        run_id=run_id,
        window_id=window_id,
        page_no=16,
        request_manifest_id=request_id,
        body_sha=receipt.body_sha,
        item_count=100,
        total_count=4935,
        status_code=200,
        content_type=receipt.content_type,
    )

    first_id = test_db.ingest.create_page(page)
    second_id = test_db.ingest.create_page(page)

    assert first_id == second_id
    with connect(test_db.path) as connection:
        count = query(
            connection,
            """SELECT COUNT(*) FROM sync_pages
               WHERE run_id = ? AND window_id = ? AND page_no = ?""",
            (run_id, window_id, 16),
        ).fetchone()
    assert count == (1,)


def test_create_page_retry_with_different_content_keeps_first_capture(
    tmp_path: Path,
) -> None:
    """A live re-fetch of an already-captured page (e.g. a retroactively
    amended change-date window) must resume cleanly and keep the original
    capture rather than raising or overwriting it."""
    test_db = create_database(tmp_path)
    run_id, window_id, request_id = _prepare(test_db)
    first_receipt = test_db.raw.put(b'{"page":16,"v":1}', "application/json")
    test_db.ingest.register_raw_blob(first_receipt, NOW)
    first_id = test_db.ingest.create_page(
        SyncPageInput(
            run_id=run_id,
            window_id=window_id,
            page_no=16,
            request_manifest_id=request_id,
            body_sha=first_receipt.body_sha,
            item_count=100,
            total_count=4935,
            status_code=200,
            content_type=first_receipt.content_type,
        )
    )
    second_receipt = test_db.raw.put(b'{"page":16,"v":2}', "application/json")
    test_db.ingest.register_raw_blob(second_receipt, NOW)

    second_id = test_db.ingest.create_page(
        SyncPageInput(
            run_id=run_id,
            window_id=window_id,
            page_no=16,
            request_manifest_id=request_id,
            body_sha=second_receipt.body_sha,
            item_count=100,
            total_count=4935,
            status_code=200,
            content_type=second_receipt.content_type,
        )
    )

    assert second_id == first_id
    with connect(test_db.path) as connection:
        row = query(
            connection,
            "SELECT COUNT(*), MIN(body_sha) FROM sync_pages WHERE id = ?",
            (first_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == 1
    assert as_text(row[1]) == first_receipt.body_sha
