"""Bounded authenticated capture of the six official G2B contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Final, Literal

from g2b_compare.contracts.probe import (
    HTTP_OK,
    MAX_ATTEMPTS,
    CaptureBlockedError,
    CaptureContext,
    attempt_probe,
)

__all__ = ["CaptureBlockedError", "CaptureContext"]
from g2b_compare.contracts.quota import (
    QuotaManifest,
    QuotaUsage,
    probe_budget,
)
from g2b_compare.contracts.share import preflight_share_link
from g2b_compare.contracts.state import (
    ManifestTransitionEvidence,
    build_fixture,
    build_manifest_history,
    page_size_failure,
)
from g2b_compare.contracts.verification import (
    schema_failure,
    schema_fields_match,
    stable_key_failure,
)
from g2b_compare.contracts.wire import (
    ObservedPage,
    candidates,
    page_size,
    stable_keys,
)

if TYPE_CHECKING:
    from g2b_compare.contracts.manifest import ContractManifest
    from g2b_compare.contracts.quota import Operation, QuotaRow
    from g2b_compare.contracts.share import SharePreflightResult

MIN_ATTEMPTS: Final = 3
ALL_OPERATIONS: Final = "all"
MISSING_KEY: Final = "missing-key"


@dataclass(frozen=True, slots=True)
class OperationCapture:
    """Redacted evidence from one fully verified operation."""

    operation: Operation
    transitions: tuple[str, ...]
    attempt_ledger_ids: tuple[int, ...]
    selected_candidate: str
    selected_params: tuple[tuple[str, str], ...]
    required_fields: tuple[str, ...]
    stable_key_fields: tuple[str, ...]
    accepted_page_size: int
    observed_max_page_size: int
    schema_fixture_sha256: str
    source_payload_sha256: str
    fixture: bytes
    manifest_history: tuple[ContractManifest, ...]
    manifest: ContractManifest
    deep_link_supported: Literal[False]
    share_link_preflight: SharePreflightResult


def capture_all(
    context: CaptureContext,
    quota_manifest: QuotaManifest,
) -> tuple[OperationCapture, ...]:
    """Capture all operations only after exact authorization parses."""
    if not context.service_key:
        raise CaptureBlockedError(ALL_OPERATIONS, MISSING_KEY, 0)
    captures: list[OperationCapture] = []
    for row in quota_manifest.rows:
        cutoff = (context.observed_at.astimezone(UTC) - timedelta(hours=24)).isoformat()
        usage = context.repository.quota_usage(row.operation, cutoff)
        budget = probe_budget(
            row,
            QuotaUsage(operation=row.operation, consumed_attempts=usage),
        )
        if budget.allowed_http_attempts < MIN_ATTEMPTS:
            reason = (
                "low-quota-zero-call"
                if budget.remaining_attempts == 0
                else "probe-budget-below-three"
            )
            raise CaptureBlockedError(row.operation, reason, 0)
        captures.append(_capture_operation(context, row, budget.ceiling))
    return tuple(captures)


def _capture_operation(
    context: CaptureContext,
    quota: QuotaRow,
    ceiling: int,
) -> OperationCapture:
    operation = quota.operation
    attempts: list[int] = []
    selected_name, selected, discovered = _discover(
        context, operation, ceiling, attempts
    )
    discovery_attempts = tuple(attempts)
    if len(attempts) > MAX_ATTEMPTS - 2:
        raise CaptureBlockedError(
            operation, "retry-leaves-no-verification-budget", len(attempts)
        )
    identity_fields = stable_keys(operation)
    if failure := stable_key_failure(discovered.rows, identity_fields):
        raise CaptureBlockedError(operation, failure, len(attempts))
    context.repository.finish_quota(attempts[-1], HTTP_OK, success=True)
    schema = attempt_probe(
        context, operation, page_size(selected, 100), ceiling, attempts
    )
    if schema is None or not schema.rows:
        raise CaptureBlockedError(operation, "verification-empty", len(attempts))
    if failure := page_size_failure(schema.reported_page_size, require_limit=False):
        raise CaptureBlockedError(operation, failure, len(attempts))
    failure = schema_failure(discovered, schema, identity_fields)
    if failure is not None:
        raise CaptureBlockedError(operation, failure, len(attempts))
    context.repository.finish_quota(attempts[-1], HTTP_OK, success=True)
    schema_attempts = tuple(attempts)
    limit = attempt_probe(
        context, operation, page_size(selected, 1000), ceiling, attempts
    )
    if limit is None or not limit.rows:
        raise CaptureBlockedError(operation, "verification-empty", len(attempts))
    if not schema_fields_match(discovered, limit):
        raise CaptureBlockedError(
            operation, "schema-changed-at-verification", len(attempts)
        )
    if failure := stable_key_failure(limit.rows, identity_fields):
        raise CaptureBlockedError(operation, failure, len(attempts))
    observed_max_page_size = limit.reported_page_size or 0
    if failure := page_size_failure(observed_max_page_size, require_limit=True):
        raise CaptureBlockedError(operation, failure, len(attempts))
    limit_attempts = tuple(attempts)
    fixture = build_fixture(operation, limit, identity_fields)
    manifest_history, verified = build_manifest_history(
        ManifestTransitionEvidence(
            quota=quota,
            selected_candidate=selected_name,
            required_fields=discovered.fields,
            stable_key_fields=identity_fields,
            discovery_attempts=discovery_attempts,
            schema_attempts=schema_attempts,
            limit_attempts=limit_attempts,
            observed_max_page_size=observed_max_page_size,
            fixture=fixture,
            verified_at=context.observed_at,
        )
    )
    context.repository.finish_quota(attempts[-1], HTTP_OK, success=True)
    preflight = preflight_share_link(context.requester, context.share_candidate_url)
    return OperationCapture(
        operation=operation,
        transitions=tuple(str(item.state.phase) for item in manifest_history),
        attempt_ledger_ids=verified.attempt_ledger_ids,
        selected_candidate=verified.selected_candidate,
        selected_params=selected,
        required_fields=verified.required_fields,
        stable_key_fields=verified.stable_key_fields,
        accepted_page_size=verified.accepted_page_size,
        observed_max_page_size=verified.observed_max_page_size,
        schema_fixture_sha256=verified.schema_fixture_sha256,
        source_payload_sha256=limit.payload_sha256,
        fixture=fixture,
        manifest_history=manifest_history,
        manifest=manifest_history[-1],
        deep_link_supported=preflight.supported,
        share_link_preflight=preflight,
    )


def _discover(
    context: CaptureContext,
    operation: Operation,
    ceiling: int,
    attempts: list[int],
) -> tuple[str, tuple[tuple[str, str], ...], ObservedPage]:
    for ordinal, candidate in enumerate(
        candidates(operation, context.observed_at.date())
    ):
        while len(attempts) < MAX_ATTEMPTS - 1:
            page = attempt_probe(context, operation, candidate, ceiling, attempts)
            if page is None:
                if len(attempts) >= MAX_ATTEMPTS - 2:
                    raise CaptureBlockedError(
                        operation, "retry-leaves-no-verification-budget", len(attempts)
                    )
                continue
            if failure := page_size_failure(
                page.reported_page_size, require_limit=False
            ):
                raise CaptureBlockedError(operation, failure, len(attempts))
            if page.rows:
                return f"D{ordinal + 1}", candidate, page
            break
    raise CaptureBlockedError(operation, "all-discovery-empty", len(attempts))
