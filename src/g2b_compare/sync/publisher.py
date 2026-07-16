"""Operation-scoped staging overlay and atomic source publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, Protocol

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.models import SourceRecordInput, SourceSnapshotInput
from g2b_compare.db.repository import DatabaseRepository
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sync.paginator import (
    PUBLICATION_NOT_VALIDATED,
    SyncInvariantError,
    ValidatedPageSet,
)

if TYPE_CHECKING:
    from pathlib import Path

type PublicationMode = Literal["full", "delta"]
DUPLICATE_SOURCE_KEY = "duplicate-source-key"
REGISTRATION_KEY_MISMATCH = "registration-key-mismatch"


class BeforePublish(Protocol):
    """Inject a kill boundary after staging and before pointer publication."""

    def __call__(self, snapshot_id: int) -> None:
        """Observe or interrupt one fully staged snapshot."""
        ...


@dataclass(frozen=True, slots=True)
class SourceDelta:
    """One operation-scoped upsert or explicit cancellation."""

    record: SourceRecordInput
    explicit_cancel: bool = False


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Validated inputs for one operation successor publication."""

    operation: Operation
    mode: PublicationMode
    window_start: str
    window_end: str
    published_at: str
    records: tuple[SourceDelta, ...]
    validated_pages: tuple[ValidatedPageSet, ...]


@dataclass(frozen=True, slots=True)
class ActiveRecord:
    """Stable projection of one row in an operation's active source slice."""

    key: str
    product_id: str
    canonical_sha: str
    is_tombstone: bool


def publish_operation(
    database: Path,
    request: PublicationRequest,
    before_publish: BeforePublish | None = None,
) -> int:
    """Copy forward, overlay, reconcile, then atomically swap one operation pointer."""
    _require_validated(request)
    parent_id, prior = _active_records(database, request.operation)
    incoming = _unique_incoming(request.records)
    staged = _staged_records(request, prior, incoming)
    repository = DatabaseRepository(database)
    snapshot_id = repository.create_source_snapshot(
        SourceSnapshotInput(
            operation=request.operation.value,
            parent_id=parent_id,
            mode=request.mode,
            window_start=request.window_start,
            window_end=request.window_end,
            completeness="complete",
        )
    )
    for key in sorted(staged):
        repository.add_source_record(snapshot_id, request.operation.value, staged[key])
    if before_publish is not None:
        before_publish(snapshot_id)
    repository.publish_source_snapshot(snapshot_id, request.published_at)
    return snapshot_id


def _require_validated(request: PublicationRequest) -> None:
    scopes = tuple(item.scope for item in request.validated_pages)
    if not scopes or any(scope is None for scope in scopes):
        raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
    concrete = tuple(scope for scope in scopes if scope is not None)
    if tuple(sorted(concrete, key=lambda item: item.window_start)) != concrete:
        raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
    expected_operation = request.operation.value
    if any(scope.operation != expected_operation for scope in concrete):
        raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
    if (
        concrete[0].window_start != request.window_start
        or concrete[-1].window_end != request.window_end
    ):
        raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
    for previous, current in pairwise(concrete):
        expected_start = date.fromisoformat(previous.window_end) + timedelta(days=1)
        if date.fromisoformat(current.window_start) != expected_start:
            raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
    if any(
        not validation.authorizes(scope)
        for validation, scope in zip(
            request.validated_pages,
            concrete,
            strict=True,
        )
    ):
        raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)


def active_records(database: Path, operation: Operation) -> tuple[ActiveRecord, ...]:
    """Read the deterministic active row projection for one operation."""
    _snapshot_id, records = _active_records(database, operation)
    return tuple(
        ActiveRecord(key, row.product_id, row.canonical_record_sha, row.is_tombstone)
        for key, row in sorted(records.items())
    )


def active_source_digest(database: Path) -> str:
    """Hash the exact five-source active pointers and canonical row projections."""
    payload: list[tuple[str, int, tuple[tuple[str, str, str, bool], ...]]] = []
    for operation in tuple(Operation)[:5]:
        snapshot_id, records = _active_records(database, operation)
        rows = tuple(
            (
                key,
                value.product_id,
                value.canonical_record_sha,
                value.is_tombstone,
            )
            for key, value in sorted(records.items())
        )
        payload.append((operation.value, snapshot_id or 0, rows))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _unique_incoming(records: tuple[SourceDelta, ...]) -> dict[str, SourceDelta]:
    incoming: dict[str, SourceDelta] = {}
    for delta in records:
        key = delta.record.source_record_key
        if key in incoming:
            raise SyncInvariantError(DUPLICATE_SOURCE_KEY)
        incoming[key] = delta
    return incoming


def _staged_records(
    request: PublicationRequest,
    prior: dict[str, SourceRecordInput],
    incoming: dict[str, SourceDelta],
) -> dict[str, SourceRecordInput]:
    staged = dict(prior)
    if request.mode == "full":
        for key, record in prior.items():
            if key not in incoming:
                staged[key] = replace(record, is_tombstone=True)
    for key, delta in incoming.items():
        previous = prior.get(key)
        if delta.explicit_cancel and (
            previous is None or previous.product_id != delta.record.product_id
        ):
            raise SyncInvariantError(REGISTRATION_KEY_MISMATCH)
        staged[key] = replace(delta.record, is_tombstone=delta.explicit_cancel)
    return staged


def _active_records(
    database: Path,
    operation: Operation,
) -> tuple[int | None, dict[str, SourceRecordInput]]:
    with connect(database) as connection:
        pointer = query(
            connection,
            "SELECT snapshot_id FROM active_source_snapshots WHERE operation = ?",
            (operation.value,),
        ).fetchone()
        if pointer is None:
            return None, {}
        snapshot_id = as_int(pointer[0])
        rows = query(
            connection,
            """SELECT source_record_key, product_id, origin_page_id,
                      raw_fields_json, payload_sha, canonical_record_sha, is_tombstone
               FROM source_records WHERE source_snapshot_id = ? AND operation = ?""",
            (snapshot_id, operation.value),
        ).fetchall()
    records = {
        as_text(row[0]): SourceRecordInput(
            source_record_key=as_text(row[0]),
            product_id=as_text(row[1]),
            origin_page_id=as_int(row[2]),
            raw_fields_json=as_text(row[3]),
            payload_sha=as_text(row[4]),
            canonical_record_sha=as_text(row[5]),
            is_tombstone=bool(as_int(row[6])),
        )
        for row in rows
    }
    return snapshot_id, records
