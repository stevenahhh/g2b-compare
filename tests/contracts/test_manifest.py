from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from g2b_compare.contracts.manifest import (
    ContractManifest,
    DiscoverState,
    ProbePhase,
    VerifiedState,
    serialize_manifest,
)
from g2b_compare.contracts.quota import Operation, QuotaRow, service_id_for

OBSERVED_AT = datetime(2026, 7, 15, tzinfo=UTC)
SOURCE_SHA = "b" * 64


def _quota(operation: Operation) -> QuotaRow:
    return QuotaRow.model_validate(
        {
            "service_id": service_id_for(operation),
            "operation": operation,
            "approved": True,
            "daily_quota": 1000,
            "reset_timezone": "unknown",
            "reset_window": "unknown",
            "observed_at": OBSERVED_AT,
            "source_sha256": SOURCE_SHA,
        }
    )


def test_manifest_parses_discover_state_as_a_typed_variant() -> None:
    # Given: an untrusted manifest mapping at the initial probe phase.
    payload = {
        "operation": Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        "quota": _quota(Operation.GET_MAS_CONTRACT_PRODUCT_INFO),
        "state": {"phase": ProbePhase.DISCOVER, "attempt_ledger_ids": ()},
    }

    # When: the manifest crosses the Pydantic boundary.
    manifest = ContractManifest.model_validate(payload)

    # Then: the state is the immutable DISCOVER variant.
    assert isinstance(manifest.state, DiscoverState)


def test_verified_manifest_is_byte_deterministic() -> None:
    # Given: a complete live-observed contract state with unordered field input.
    operation = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
    state = VerifiedState(
        attempt_ledger_ids=(11, 12, 13),
        selected_candidate="workbook-product-1",
        required_fields=("attrVal", "prdctIdntNo", "attrNm"),
        stable_key_fields=("prdctIdntNo", "attrNm"),
        accepted_page_size=100,
        observed_max_page_size=1000,
        schema_fixture_sha256="c" * 64,
        verified_at=OBSERVED_AT,
        provenance="live_observed",
        quota_scope="operation",
        quota_reset_source="unknown",
    )
    manifest = ContractManifest(
        operation=operation, quota=_quota(operation), state=state
    )

    # When: the same immutable manifest is serialized twice.
    first = serialize_manifest(manifest)
    second = serialize_manifest(manifest)

    # Then: bytes and canonical field ordering are stable.
    assert first == second
    assert b'"required_fields":["attrNm","attrVal","prdctIdntNo"]' in first
    assert first.endswith(b"\n")


def test_manifest_rejects_quota_for_another_operation() -> None:
    # Given: a state row paired with another operation's quota authorization.
    payload = {
        "operation": Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        "quota": _quota(Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE),
        "state": {"phase": ProbePhase.DISCOVER, "attempt_ledger_ids": ()},
    }

    # When/Then: operation identity cannot cross the boundary inconsistently.
    with pytest.raises(ValidationError, match="quota operation"):
        _ = ContractManifest.model_validate(payload)


def test_verified_state_rejects_duplicate_attempt_ledger_ids() -> None:
    # Given/When/Then: each HTTP attempt must have one distinct ledger identity.
    with pytest.raises(ValidationError, match="attempt ledger IDs"):
        _ = VerifiedState(
            attempt_ledger_ids=(7, 7, 8),
            selected_candidate="candidate",
            required_fields=("id",),
            stable_key_fields=("id",),
            accepted_page_size=100,
            observed_max_page_size=100,
            schema_fixture_sha256="d" * 64,
            verified_at=OBSERVED_AT,
            provenance="live_observed",
            quota_scope="operation",
            quota_reset_source="unknown",
        )
