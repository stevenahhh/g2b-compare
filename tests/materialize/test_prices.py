from __future__ import annotations

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.materialize.prices import comparison_price
from g2b_compare.materialize.products import merge_products

from .support import OfferOverride, offer


def test_minimum_active_positive_price_uses_one_normalized_unit() -> None:
    # Given
    product = merge_products(
        (
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(price="1,200,000"),
            ),
            offer(
                Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
                "B",
                OfferOverride(price="1100000"),
            ),
        ),
        (),
    )[0]

    # When
    price = comparison_price(product.offers)

    # Then
    assert (price.active, price.amount_won, price.unit_key) == (True, 1100000, "대")
    assert price.offer_key == (Operation.GET_UNIT_CONTRACT_PRODUCT_INFO.value, "B")


@pytest.mark.parametrize(
    ("raw_price", "reason"),
    [("", "missing-price"), ("0", "zero-price"), ("-1", "negative-price")],
)
def test_missing_or_nonpositive_contract_price_is_inactive(
    raw_price: str,
    reason: str,
) -> None:
    # Given
    product = merge_products(
        (
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(price=raw_price),
            ),
        ),
        (),
    )[0]

    # When
    price = comparison_price(product.offers)

    # Then
    assert (price.active, price.amount_won, price.reason) == (False, None, reason)


def test_mixed_units_are_inactive_and_product_unit_price_is_provenance_only() -> None:
    # Given
    product = merge_products(
        (
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(price="1200000"),
            ),
            offer(
                Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
                "B",
                OfferOverride(price="1100000", unit="식"),
            ),
        ),
        (),
    )[0]

    # When
    price = comparison_price(product.offers)

    # Then
    assert (price.active, price.amount_won, price.reason) == (
        False,
        None,
        "mixed-unit",
    )
    assert product.offers[0].product_unit_price_raw == "1190000"
