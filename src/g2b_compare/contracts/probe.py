"""Quota-ledgered HTTP probe execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, override

import httpx

from g2b_compare.contracts.wire import (
    ObservedPage,
    Requester,
    WireContractError,
    official_url,
    parse_page,
)
from g2b_compare.db.models import QuotaReservationInput

if TYPE_CHECKING:
    from g2b_compare.contracts.quota import Operation
    from g2b_compare.db.ingest import IngestRepository

HTTP_OK: Final = 200
MAX_ATTEMPTS: Final = 5
RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class CaptureBlockedError(Exception):
    """Sanitized fail-closed capture result."""

    operation: str
    reason: str
    http_calls: int
    status_code: int | None = None

    @override
    def __str__(self) -> str:
        return f"contract capture blocked: {self.reason} ({self.operation})"


@dataclass(frozen=True, slots=True)
class CaptureContext:
    """Runtime-only secret and outbound dependencies."""

    requester: Requester
    repository: IngestRepository
    service_key: str
    observed_at: datetime
    share_candidate_url: str | None = None


def attempt_probe(
    context: CaptureContext,
    operation: Operation,
    keyless_params: tuple[tuple[str, str], ...],
    ceiling: int,
    attempts: list[int],
) -> ObservedPage | None:
    """Reserve, execute, and persist a non-success outcome until acceptance."""
    if len(attempts) >= MAX_ATTEMPTS:
        raise CaptureBlockedError(operation, "probe-call-6", len(attempts))
    try:
        url = official_url(operation)
    except WireContractError as error:
        raise CaptureBlockedError(operation, error.reason, len(attempts)) from None
    now = context.observed_at.astimezone(UTC)
    reservation = context.repository.reserve_quota(
        QuotaReservationInput(
            operation=operation,
            attempted_at_utc=now.isoformat(),
            cutoff_utc=(now - timedelta(hours=24)).isoformat(),
            kst_date=context.observed_at.date().isoformat(),
            ceiling=ceiling,
        )
    )
    attempts.append(reservation)
    params = (*keyless_params, ("serviceKey", context.service_key))
    try:
        response = context.requester.get(url, params=params, follow_redirects=False)
    except httpx.TimeoutException:
        context.repository.finish_quota(reservation, 0, success=False)
        return None
    status = response.status_code
    context.repository.finish_quota(reservation, status, success=False)
    if status in RETRYABLE_STATUSES:
        return None
    if httpx.codes.MULTIPLE_CHOICES <= status < httpx.codes.BAD_REQUEST:
        raise CaptureBlockedError(
            operation,
            "redirect-response-zero-followup",
            len(attempts),
            status,
        )
    if status != HTTP_OK:
        reason = "401-text" if status in {401, 403} else "http-status"
        raise CaptureBlockedError(operation, reason, len(attempts), status)
    if "application/json" not in response.headers.get("content-type", "").casefold():
        raise CaptureBlockedError(
            operation, "200-wrong-content-type", len(attempts)
        )
    try:
        return parse_page(response.content, operation)
    except WireContractError as error:
        raise CaptureBlockedError(operation, error.reason, len(attempts)) from None
