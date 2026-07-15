"""Request, page, raw-blob, and quota persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .connection import connect
from .hashes import request_identity
from .repository import RepositoryContractError
from .sql import ResultCursor, as_int, as_text, query

if TYPE_CHECKING:
    from pathlib import Path

    from .models import (
        QuotaReservationInput,
        RawBlobReceipt,
        RequestInput,
        SyncPageInput,
        SyncRunInput,
        SyncWindowInput,
    )

ALLOWLISTED_PARAMETER_NAMES: Final = frozenset(
    {
        "chgDtBgnDt",
        "chgDtEndDt",
        "cntrctCorpNm",
        "inqryDiv",
        "numOfRows",
        "pageNo",
        "prdctClsfcNoNm",
        "prdctIdntNo",
        "prodctCertYn",
        "rgstDtBgnDt",
        "rgstDtEndDt",
        "stdt",
        "type",
    }
)
SECRET_PARAMETER_MARKERS: Final = ("auth", "credential", "key", "secret", "token")


@dataclass(frozen=True, slots=True)
class IngestRepository:
    """Transaction boundary for captured requests, pages, and call budget."""

    database: Path

    def create_run(self, run: SyncRunInput) -> int:
        """Create one source synchronization run."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                """
                INSERT INTO sync_runs(
                    operation, mode, status, cursor_json, page_size,
                    calls, started_at
                ) VALUES (?, ?, 'running', '{}', ?, 0, ?)
                """,
                (run.operation, run.mode, run.page_size, run.started_at),
            )
            return _row_id(cursor)

    def create_window(self, window: SyncWindowInput) -> int:
        """Persist an ordered window whose page numbers are window-local."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                """
                INSERT INTO sync_windows(run_id, ordinal, window_start, window_end)
                VALUES (?, ?, ?, ?)
                """,
                (
                    window.run_id,
                    window.ordinal,
                    window.window_start,
                    window.window_end,
                ),
            )
            return _row_id(cursor)

    def create_page(self, page: SyncPageInput) -> int:
        """Persist one verified page, allowing page one in distinct windows."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                """
                INSERT INTO sync_pages(
                    run_id, window_id, page_no, request_manifest_id, body_sha,
                    item_count, total_count, status_code, content_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page.run_id,
                    page.window_id,
                    page.page_no,
                    page.request_manifest_id,
                    page.body_sha,
                    page.item_count,
                    page.total_count,
                    page.status_code,
                    page.content_type,
                ),
            )
            return _row_id(cursor)

    def register_request(self, request: RequestInput) -> int:
        """Persist a secret-free canonical request or return its exact replay."""
        for key, _value in request.params:
            normalized_key = "".join(
                character for character in key if character.isalnum()
            )
            if any(
                marker in normalized_key.casefold()
                for marker in SECRET_PARAMETER_MARKERS
            ):
                raise RepositoryContractError(
                    detail=f"secret parameter is not allowlisted: {key}"
                )
            if key not in ALLOWLISTED_PARAMETER_NAMES:
                raise RepositoryContractError(
                    detail=f"parameter is not allowlisted: {key}"
                )
        params_json, params_sha, fingerprint = request_identity(request)
        with connect(self.database) as connection:
            existing = query(
                connection,
                """
                SELECT id, operation, method, official_path, params_json_without_key
                FROM request_manifests WHERE request_fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
            expected = (
                request.operation,
                request.method,
                request.official_path,
                params_json,
            )
            if existing is not None:
                actual = tuple(as_text(value) for value in existing[1:])
                if actual != expected:
                    raise RepositoryContractError(
                        detail="request fingerprint collision detected"
                    )
                return as_int(existing[0])
            cursor = query(
                connection,
                """
                INSERT INTO request_manifests(
                    operation, method, official_path, params_json_without_key,
                    params_sha, request_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.operation,
                    request.method,
                    request.official_path,
                    params_json,
                    params_sha,
                    fingerprint,
                    request.created_at,
                ),
            )
            return _row_id(cursor)

    def register_raw_blob(self, receipt: RawBlobReceipt, created_at: str) -> None:
        """Register a verified content-addressed raw file idempotently."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """
                INSERT INTO raw_blobs(
                    body_sha, raw_path, content_type, byte_count, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(body_sha) DO NOTHING
                """,
                (
                    receipt.body_sha,
                    str(receipt.path),
                    receipt.content_type,
                    receipt.byte_count,
                    created_at,
                ),
            )

    def reserve_quota(self, quota: QuotaReservationInput) -> int:
        """Atomically consume one rolling-window call before network I/O."""
        if quota.ceiling <= 0:
            raise RepositoryContractError(detail="quota ceiling exhausted")
        with connect(self.database) as connection:
            _ = query(connection, "BEGIN IMMEDIATE")
            row = query(
                connection,
                """
                SELECT COUNT(*) FROM api_call_ledger
                WHERE operation = ? AND attempted_at_utc >= ?
                """,
                (quota.operation, quota.cutoff_utc),
            ).fetchone()
            count = 0 if row is None else as_int(row[0])
            if count >= quota.ceiling:
                raise RepositoryContractError(detail="quota ceiling exhausted")
            cursor = query(
                connection,
                """
                INSERT INTO api_call_ledger(
                    operation, attempted_at_utc, kst_date, reservation_state
                ) VALUES (?, ?, ?, 'reserved')
                """,
                (quota.operation, quota.attempted_at_utc, quota.kst_date),
            )
            reservation_id = _row_id(cursor)
            _ = query(connection, "COMMIT")
            return reservation_id

    def finish_quota(
        self,
        reservation_id: int,
        status_code: int,
        success: bool,
    ) -> None:
        """Record an outcome without refunding its prior reservation."""
        state = "succeeded" if success else "failed"
        with connect(self.database) as connection:
            _ = query(
                connection,
                """
                UPDATE api_call_ledger
                SET status_code = ?, reservation_state = ? WHERE id = ?
                """,
                (status_code, state, reservation_id),
            )


def _row_id(cursor: ResultCursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RepositoryContractError(detail="SQLite did not return a row id")
    return row_id
