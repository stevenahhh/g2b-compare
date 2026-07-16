from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from g2b_compare.ranking.formula import quantize_score, value_similarity


def test_value_similarity_is_symmetric_and_quantized() -> None:
    forward = value_similarity(Decimal(8), Decimal(10))
    reverse = value_similarity(Decimal(10), Decimal(8))

    assert forward is not None
    assert forward == pytest.approx(reverse)
    assert quantize_score(forward) == Decimal("0.367879")


def test_value_similarity_rejects_nonpositive_values() -> None:
    assert value_similarity(Decimal(0), Decimal(1)) is None


@given(
    left=st.integers(min_value=1, max_value=10_000_000),
    right=st.integers(min_value=1, max_value=10_000_000),
)
def test_value_and_price_kernel_are_symmetric(left: int, right: int) -> None:
    assert value_similarity(Decimal(left), Decimal(right)) == value_similarity(
        Decimal(right), Decimal(left)
    )
