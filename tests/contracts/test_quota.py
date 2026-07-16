from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from g2b_compare.contracts.quota import (
    Operation,
    QuotaManifest,
    QuotaRow,
    QuotaUsage,
    effective_ceiling,
    probe_budget,
    service_id_for,
)

OBSERVED_AT = datetime(2026, 7, 15, tzinfo=UTC)
SOURCE_SHA = "a" * 64


def _row(operation: Operation, *, approved: bool = True) -> QuotaRow:
    return QuotaRow.model_validate(
        {
            "service_id": service_id_for(operation),
            "operation": operation,
            "approved": approved,
            "daily_quota": 1000,
            "reset_timezone": "unknown",
            "reset_window": "unknown",
            "observed_at": OBSERVED_AT,
            "source_sha256": SOURCE_SHA,
        }
    )


def test_manifest_accepts_exact_six_approved_operations() -> None:
    # Given: every separately approved operation in reverse input order.
    rows = tuple(_row(operation) for operation in reversed(tuple(Operation)))

    # When: the external quota observation crosses the typed boundary.
    manifest = QuotaManifest(rows=rows)

    # Then: the persisted order is canonical and contains exactly six rows.
    assert tuple(row.operation for row in manifest.rows) == tuple(Operation)


def test_manifest_rejects_a_missing_operation() -> None:
    # Given: an account observation without the separately approved attribute row.
    rows = tuple(_row(operation) for operation in tuple(Operation)[:-1])

    # When/Then: the six-operation boundary rejects it.
    with pytest.raises(ValidationError, match="six approved operations"):
        _ = QuotaManifest(rows=rows)


def test_quota_row_rejects_unapproved_status() -> None:
    # Given/When/Then: an unapproved row cannot become an internal quota row.
    with pytest.raises(ValidationError, match="approved"):
        _ = _row(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, approved=False)


def test_effective_ceiling_reserves_ten_percent_or_one_hundred() -> None:
    # Given: the observed daily quota is 1,000.
    row = _row(Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE)

    # When: the safety ceiling is calculated.
    ceiling = effective_ceiling(row)

    # Then: 100 calls are reserved and 900 remain available.
    assert ceiling == 900


@pytest.mark.parametrize(("consumed", "expected"), [(897, 3), (898, 0), (900, 0)])
def test_probe_budget_allows_zero_calls_when_fewer_than_three_remain(
    consumed: int,
    expected: int,
) -> None:
    # Given: a verified quota row and a deterministic rolling usage count.
    row = _row(Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE)
    usage = QuotaUsage(operation=row.operation, consumed_attempts=consumed)

    # When: the bounded contract-probe budget is derived.
    budget = probe_budget(row, usage)

    # Then: DISCOVER plus two VERIFY calls are indivisible.
    assert budget.allowed_http_attempts == expected
