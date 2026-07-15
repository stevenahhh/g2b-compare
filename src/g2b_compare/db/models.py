"""Typed inputs and receipts for SQLite persistence boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceSnapshotInput:
    """Fields needed to create one unpublished source snapshot."""

    operation: str
    parent_id: int | None
    mode: str
    window_start: str
    window_end: str
    completeness: str


@dataclass(frozen=True, slots=True)
class SourceRecordInput:
    """One immutable provider row with raw and canonical provenance."""

    source_record_key: str
    product_id: str
    origin_page_id: int
    raw_fields_json: str
    payload_sha: str
    canonical_record_sha: str
    is_tombstone: bool = False


@dataclass(frozen=True, slots=True)
class CanonicalSourceRecord:
    """Media-neutral provider fields used by product change detection."""

    operation: str
    stable_source_key: str
    product_id: str
    category: str
    detail_category: str
    product_name: str
    spec_name: str
    detail: str
    characteristic: str
    active: bool
    unit_basis: str


@dataclass(frozen=True, slots=True)
class RequestInput:
    """One keyless allowlisted HTTP request identity."""

    operation: str
    method: str
    official_path: str
    params: tuple[tuple[str, str], ...]
    created_at: str


@dataclass(frozen=True, slots=True)
class RawBlobReceipt:
    """Verified immutable raw blob ready for database registration."""

    body_sha: str
    path: Path
    content_type: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class StagedRawBlob:
    """Fsynced gzip awaiting its single atomic publication step."""

    receipt: RawBlobReceipt
    temporary_path: Path


@dataclass(frozen=True, slots=True)
class QuotaReservationInput:
    """Rolling-window facts required for an atomic call reservation."""

    operation: str
    attempted_at_utc: str
    cutoff_utc: str
    kst_date: str
    ceiling: int


@dataclass(frozen=True, slots=True)
class AttributeStateInput:
    """One product state in an attribute snapshot successor."""

    product_id: str
    fetch_status: str
    source_fingerprint_sha: str
    completed_at: str | None
    origin_snapshot_id: int | None


@dataclass(frozen=True, slots=True)
class AttributeRecordInput:
    """One attribute row retaining its original response page."""

    product_id: str
    attribute_source_key: str
    origin_page_id: int
    raw_fields_json: str
    payload_sha: str


@dataclass(frozen=True, slots=True)
class SyncRunInput:
    """One source synchronization run boundary."""

    operation: str
    mode: str
    started_at: str
    page_size: int = 100


@dataclass(frozen=True, slots=True)
class SyncWindowInput:
    """One deterministic ordered window within a run."""

    run_id: int
    ordinal: int
    window_start: str
    window_end: str


@dataclass(frozen=True, slots=True)
class SyncPageInput:
    """One verified page and its request/raw provenance."""

    run_id: int
    window_id: int
    page_no: int
    request_manifest_id: int
    body_sha: str
    item_count: int
    total_count: int
    status_code: int
    content_type: str
