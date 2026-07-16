from __future__ import annotations

import pytest

from g2b_compare.contracts.state import page_size_failure


@pytest.mark.parametrize("reported", (0, -1, 1001), ids=("zero", "negative", "over-max"))
def test_verify_limit_rejects_reported_size_outside_positive_range(
    reported: int,
) -> None:
    # Given: a provider-reported size outside the accepted 1..1000 range.
    # When: VERIFY_LIMIT validates the reported pagination evidence.
    failure = page_size_failure(reported, require_limit=True)

    # Then: the limit remains unproven.
    assert failure == "limit-unproven"
