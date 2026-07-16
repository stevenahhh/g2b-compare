"""Restartable raw-page evidence for attribute responses."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final, override

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.models import (
    RawBlobReceipt,
    RequestInput,
    SyncPageInput,
    SyncRunInput,
    SyncWindowInput,
)
from g2b_compare.db.raw import RawBlobStore
from g2b_compare.db.sql import as_int, as_text, query

_OPERATION: Final = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
_REQUEST_DRIFT: Final = "repeated-page-request-drift"
_BODY_DRIFT: Final = "repeated-page-body-drift"


@final
class AttributeEvidenceError(Exception):
    """Reject conflicting persisted evidence without exposing response data."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one sanitized evidence reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class PreparedAttributeEvidence:
    """Persisted request identity and restartable product run."""

    run_id: int
    window_id: int
    request_id: int
    page_no: int


@dataclass(frozen=True, slots=True)
class AttributeEvidenceRequest:
    """One secret-free attribute request prepared for durable staging."""

    generation_id: int
    product_id: str
    page_no: int
    page_size: int
    official_path: str
    params: tuple[tuple[str, str], ...]
    created_at: str


@dataclass(frozen=True, slots=True)
class AttributeEvidenceRecord:
    """One verified attribute response ready for durable staging."""

    content: bytes
    content_type: str
    item_count: int
    total_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class StoredAttributeResponse:
    """One verified raw response recovered without another HTTP call."""

    page_id: int
    content: bytes
    content_type: str
    status_code: int


@dataclass(frozen=True, slots=True)
class AttributeEvidenceStore:
    """Persist and resume attribute pages through Todo3 raw/page tables."""

    database: Path
    raw_root: Path

    def prepare(self, request: AttributeEvidenceRequest) -> PreparedAttributeEvidence:
        """Create or reopen the exact product-generation staging run."""
        repository = IngestRepository(self.database)
        request_id = repository.register_request(
            RequestInput(
                operation=_OPERATION,
                method="GET",
                official_path=request.official_path,
                params=request.params,
                created_at=request.created_at,
            )
        )
        mode = (
            f"attribute:{request.generation_id}:{request.product_id}:"
            f"{request.page_size}"
        )
        with connect(self.database) as connection:
            row = query(
                connection,
                """SELECT runs.id, windows.id
                FROM sync_runs AS runs
                JOIN sync_windows AS windows ON windows.run_id = runs.id
                WHERE runs.operation = ? AND runs.mode = ?
                  AND runs.status = 'running' AND windows.ordinal = 0
                ORDER BY runs.id DESC LIMIT 1""",
                (_OPERATION, mode),
            ).fetchone()
        if row is None:
            run_id = repository.create_run(
                SyncRunInput(_OPERATION, mode, request.created_at, request.page_size)
            )
            window_id = repository.create_window(
                SyncWindowInput(run_id, 0, request.created_at, request.created_at)
            )
        else:
            run_id, window_id = as_int(row[0]), as_int(row[1])
        return PreparedAttributeEvidence(run_id, window_id, request_id, request.page_no)

    def load(
        self, prepared: PreparedAttributeEvidence
    ) -> StoredAttributeResponse | None:
        """Recover a fully staged page for a zero-call restart."""
        with connect(self.database) as connection:
            row = query(
                connection,
                """SELECT pages.id, pages.request_manifest_id, pages.status_code,
                          blobs.raw_path, blobs.content_type, blobs.body_sha,
                          blobs.byte_count
                FROM sync_pages AS pages
                JOIN raw_blobs AS blobs ON blobs.body_sha = pages.body_sha
                WHERE pages.run_id = ? AND pages.window_id = ? AND pages.page_no = ?""",
                (prepared.run_id, prepared.window_id, prepared.page_no),
            ).fetchone()
        if row is None:
            return None
        if as_int(row[1]) != prepared.request_id:
            raise AttributeEvidenceError(_REQUEST_DRIFT)
        receipt = RawBlobReceipt(
            body_sha=as_text(row[5]),
            path=Path(as_text(row[3])),
            content_type=as_text(row[4]),
            byte_count=as_int(row[6]),
        )
        RawBlobStore(self.raw_root).verify(receipt)
        return StoredAttributeResponse(
            page_id=as_int(row[0]),
            content=gzip.decompress(receipt.path.read_bytes()),
            content_type=receipt.content_type,
            status_code=as_int(row[2]),
        )

    def record(
        self,
        prepared: PreparedAttributeEvidence,
        response: AttributeEvidenceRecord,
    ) -> int:
        """Atomically expose raw bytes, then idempotently stage their page."""
        raw = RawBlobStore(self.raw_root)
        receipt = raw.put(response.content, response.content_type)
        repository = IngestRepository(self.database)
        repository.register_raw_blob(receipt, response.created_at)
        existing = self.load(prepared)
        if existing is not None:
            if existing.content != response.content:
                raise AttributeEvidenceError(_BODY_DRIFT)
            return existing.page_id
        return repository.create_page(
            SyncPageInput(
                run_id=prepared.run_id,
                window_id=prepared.window_id,
                page_no=prepared.page_no,
                request_manifest_id=prepared.request_id,
                body_sha=receipt.body_sha,
                item_count=response.item_count,
                total_count=response.total_count,
                status_code=200,
                content_type=response.content_type,
            )
        )
