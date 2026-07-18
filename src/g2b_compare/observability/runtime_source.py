"""Persist and reconstruct source pages for runtime publication."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from g2b_compare.contracts.wire import official_url, parse_page, stable_keys
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.models import RequestInput, SourceRecordInput, SyncPageInput
from g2b_compare.db.raw import RawBlobStore
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sync.publisher import SourceDelta

if TYPE_CHECKING:
    from g2b_compare.contracts.quota import Operation
    from g2b_compare.contracts.redact import JsonScalar

CANCELLED: Final = frozenset({"y", "n/a", "취소", "삭제", "종료", "cancelled"})
RUNNING_WINDOW_MISSING: Final = "running-window-missing"


@dataclass(frozen=True, slots=True)
class PageEvidence:
    """Raw response facts persisted before checkpoint advancement."""

    content: bytes
    content_type: str
    page_no: int
    item_count: int
    total_count: int


@dataclass(frozen=True, slots=True)
class PagePersistence:
    """Context required to persist one verified source page."""

    database: Path
    operation: Operation
    window_start: str
    window_end: str
    params: tuple[tuple[str, str], ...]
    evidence: PageEvidence


@dataclass(frozen=True, slots=True)
class SourcePersistenceError(RuntimeError):
    """Typed missing-run persistence failure."""

    reason: str


def persist_page(request: PagePersistence) -> int:
    """Persist one verified raw response and its request/page provenance."""
    observed_at = datetime.now(UTC).isoformat()
    repository = IngestRepository(request.database)
    receipt = RawBlobStore(request.database.parent / "raw").put(
        request.evidence.content,
        request.evidence.content_type,
    )
    repository.register_raw_blob(receipt, observed_at)
    request_id = repository.register_request(
        RequestInput(
            request.operation.value,
            "GET",
            urlsplit(official_url(request.operation)).path,
            request.params,
            observed_at,
        )
    )
    with connect(request.database) as connection:
        row = query(
            connection,
            """SELECT runs.id, windows.id
               FROM sync_runs AS runs
               JOIN sync_windows AS windows ON windows.run_id=runs.id
               WHERE runs.operation=? AND runs.status='running'
                 AND windows.window_start=? AND windows.window_end=?
               ORDER BY runs.id DESC LIMIT 1""",
            (
                request.operation.value,
                request.window_start,
                request.window_end,
            ),
        ).fetchone()
    if row is None:
        raise SourcePersistenceError(RUNNING_WINDOW_MISSING)
    return repository.create_page(
        SyncPageInput(
            as_int(row[0]),
            as_int(row[1]),
            request.evidence.page_no,
            request_id,
            receipt.body_sha,
            request.evidence.item_count,
            request.evidence.total_count,
            200,
            request.evidence.content_type,
        )
    )


def run_records(
    database: Path,
    operation: Operation,
    run_id: int,
) -> tuple[SourceDelta, ...]:
    """Reconstruct every persisted page in a run into publication records."""
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT pages.id, blobs.raw_path
               FROM sync_pages AS pages
               JOIN raw_blobs AS blobs ON blobs.body_sha=pages.body_sha
               WHERE pages.run_id=? ORDER BY pages.window_id, pages.page_no""",
            (run_id,),
        ).fetchall()
    result: list[SourceDelta] = []
    for row in rows:
        path = Path(as_text(row[1]))
        with gzip.open(path, "rb") as stream:
            page = parse_page(stream.read(), operation)
        for raw in page.rows:
            record = _source_record(operation, as_int(row[0]), raw)
            if record is not None:
                result.append(record)
    return tuple(result)


def _source_record(
    operation: Operation,
    page_id: int,
    raw: dict[str, JsonScalar],
) -> SourceDelta | None:
    values = tuple(_text(raw.get(field)) for field in stable_keys(operation))
    product_id = _text(raw.get("prdctIdntNo"))
    if not product_id or any(not value for value in values):
        return None
    raw_json = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload_sha = hashlib.sha256(raw_json.encode()).hexdigest()
    key = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    canonical = json.dumps(
        (operation.value, values, product_id, raw),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return SourceDelta(
        SourceRecordInput(
            key,
            product_id,
            page_id,
            raw_json,
            payload_sha,
            hashlib.sha256(canonical.encode()).hexdigest(),
        ),
        _is_cancelled(raw),
    )


def _is_cancelled(raw: dict[str, JsonScalar]) -> bool:
    flags = ("cntrctCnclYn", "delYn")
    if any(_text(raw.get(field)).casefold() == "y" for field in flags):
        return True
    if _text(raw.get("useYn")).casefold() == "n":
        return True
    statuses = ("cntrctSttus", "cntrctSttusNm", "prdctSttusNm")
    return any(_text(raw.get(field)).casefold() in CANCELLED for field in statuses)


def _text(value: JsonScalar | None) -> str:
    return "" if value is None else str(value).strip()
