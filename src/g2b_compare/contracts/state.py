"""Construct typed contract-capture state histories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.manifest import (
    ContractManifest,
    DiscoverState,
    VerifiedState,
    VerifyLimitState,
    VerifySchemaState,
)
from g2b_compare.contracts.redact import JsonValue, serialize_redacted

MIN_PAGE_SIZE: Final = 1
MAX_PAGE_SIZE: Final = 1000

if TYPE_CHECKING:
    from datetime import datetime

    from g2b_compare.contracts.quota import Operation, QuotaRow
    from g2b_compare.contracts.wire import ObservedPage


@dataclass(frozen=True, slots=True)
class ManifestTransitionEvidence:
    """Inputs required to validate all typed capture phases."""

    quota: QuotaRow
    selected_candidate: str
    required_fields: tuple[str, ...]
    stable_key_fields: tuple[str, ...]
    discovery_attempts: tuple[int, ...]
    schema_attempts: tuple[int, ...]
    limit_attempts: tuple[int, ...]
    observed_max_page_size: int
    fixture: bytes
    verified_at: datetime


def build_manifest_history(
    evidence: ManifestTransitionEvidence,
) -> tuple[tuple[ContractManifest, ...], VerifiedState]:
    """Validate every phase and return the final typed verified state."""
    discover = DiscoverState(attempt_ledger_ids=evidence.discovery_attempts)
    schema = VerifySchemaState(
        attempt_ledger_ids=evidence.schema_attempts,
        selected_candidate=evidence.selected_candidate,
        required_fields=evidence.required_fields,
        stable_key_fields=evidence.stable_key_fields,
        accepted_page_size=100,
    )
    limit = VerifyLimitState(
        attempt_ledger_ids=evidence.limit_attempts,
        selected_candidate=evidence.selected_candidate,
        required_fields=evidence.required_fields,
        stable_key_fields=evidence.stable_key_fields,
        accepted_page_size=evidence.observed_max_page_size,
        observed_max_page_size=evidence.observed_max_page_size,
    )
    verified = VerifiedState(
        attempt_ledger_ids=evidence.limit_attempts,
        selected_candidate=evidence.selected_candidate,
        required_fields=evidence.required_fields,
        stable_key_fields=evidence.stable_key_fields,
        accepted_page_size=evidence.observed_max_page_size,
        observed_max_page_size=evidence.observed_max_page_size,
        schema_fixture_sha256=hashlib.sha256(evidence.fixture).hexdigest(),
        verified_at=evidence.verified_at,
        provenance="live_observed",
        quota_scope="operation",
        quota_reset_source="unknown",
    )
    states = (discover, schema, limit, verified)
    history = tuple(
        ContractManifest(
            operation=evidence.quota.operation,
            quota=evidence.quota,
            state=state,
        )
        for state in states
    )
    return history, verified


def page_size_failure(reported: int | None, *, require_limit: bool) -> str | None:
    """Return the stable failure ID for provider page-size evidence."""
    if reported is None:
        return "limit-unproven" if require_limit else "malformed-envelope"
    if require_limit and not MIN_PAGE_SIZE <= reported <= MAX_PAGE_SIZE:
        return "limit-unproven"
    return None


def build_fixture(
    operation: Operation,
    page: ObservedPage,
    keys: tuple[str, ...],
) -> bytes:
    """Build the deterministic redacted verified-schema fixture."""
    row = page.rows[0]
    safe: dict[str, JsonValue] = {key: row[key] for key in keys}
    required_fields: list[JsonValue] = []
    required_fields.extend(page.fields)
    fixture: dict[str, JsonValue] = {
        "operation": str(operation),
        "payload_sha256": page.payload_sha256,
        "required_fields": required_fields,
        "sample_stable_key": safe,
        "total_count": page.total_count,
    }
    return serialize_redacted(fixture)
