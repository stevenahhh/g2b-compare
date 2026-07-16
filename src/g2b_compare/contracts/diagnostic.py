"""Single-call sanitized provider-limit diagnostic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, override
from urllib.parse import urlsplit

import httpx

from g2b_compare.contracts.diagnostic_shapes import (
    LimitDiagnostic,
    inspect_limit_response,
)
from g2b_compare.contracts.live import load_service_key
from g2b_compare.contracts.quota import (
    Operation,
    QuotaManifest,
    effective_ceiling,
)
from g2b_compare.contracts.wire import (
    HttpxRequester,
    Requester,
    candidates,
    official_url,
    page_size,
)
from g2b_compare.db.hashes import request_identity
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import QuotaReservationInput, RequestInput

__all__ = ["inspect_limit_response"]

if TYPE_CHECKING:
    from pathlib import Path

OPERATION: Final = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
HTTP_OK: Final = 200
REQUEST_FAILED: Final = "request-failed"
PUBLICATION_BLOCKED_REASON: Final = "secret-publication-blocked"


@dataclass(frozen=True, slots=True)
class LimitDiagnosticConfig:
    """Filesystem inputs for one quota-ledgered diagnostic call."""

    output_path: Path
    ledger_path: Path
    quota_path: Path
    secret_source: Path
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    url: str
    params: tuple[tuple[str, str], ...]
    secret: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DiagnosticError(Exception):
    """Sanitized diagnostic failure."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def run_limit_diagnostic(
    config: LimitDiagnosticConfig,
    requester: Requester | None = None,
) -> LimitDiagnostic:
    """Reserve quota, make one D3 MAS limit request, and publish safe evidence."""
    secret = load_service_key(config.secret_source)
    quota = QuotaManifest.model_validate_json(config.quota_path.read_bytes())
    row = next(item for item in quota.rows if item.operation is OPERATION)
    migrate(config.ledger_path)
    repository = IngestRepository(config.ledger_path)
    params = page_size(candidates(OPERATION, config.observed_at.date())[2], 1000)
    url = official_url(OPERATION)
    fingerprint = request_identity(
        RequestInput(
            operation=OPERATION,
            method="GET",
            official_path=urlsplit(url).path,
            params=params,
            created_at=config.observed_at.isoformat(),
        )
    )[2]
    now = config.observed_at.astimezone(UTC)
    reservation = repository.reserve_quota(
        QuotaReservationInput(
            operation=OPERATION,
            attempted_at_utc=now.isoformat(),
            cutoff_utc=(now - timedelta(hours=24)).isoformat(),
            kst_date=config.observed_at.date().isoformat(),
            ceiling=effective_ceiling(row),
        )
    )
    if requester is not None:
        return _execute(
            config,
            requester,
            repository,
            reservation,
            _PreparedRequest(url, params, secret, fingerprint),
        )
    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10),
    ) as client:
        return _execute(
            config,
            HttpxRequester(client),
            repository,
            reservation,
            _PreparedRequest(url, params, secret, fingerprint),
        )


def _execute(
    config: LimitDiagnosticConfig,
    requester: Requester,
    repository: IngestRepository,
    reservation: int,
    request: _PreparedRequest,
) -> LimitDiagnostic:
    try:
        response = requester.get(
            request.url,
            params=(*request.params, ("serviceKey", request.secret)),
            follow_redirects=False,
        )
    except httpx.RequestError:
        repository.finish_quota(reservation, 0, success=False)
        raise DiagnosticError(REQUEST_FAILED) from None
    repository.finish_quota(
        reservation, response.status_code, success=response.status_code == HTTP_OK
    )
    result = inspect_limit_response(
        response.status_code,
        response.headers.get("content-type", ""),
        response.content,
        request_fingerprint=request.fingerprint,
        secret_values=(request.secret,),
    )
    content = result.model_dump_json().encode() + b"\n"
    if request.secret.encode() in content:
        raise DiagnosticError(PUBLICATION_BLOCKED_REASON)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    _ = temporary.write_bytes(content)
    _ = temporary.replace(config.output_path)
    return result
