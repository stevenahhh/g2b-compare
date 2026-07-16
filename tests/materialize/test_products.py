from __future__ import annotations

from g2b_compare.contracts.quota import Operation
from g2b_compare.materialize.products import RegistrationCancellation, merge_products

from .support import OfferOverride, offer


def test_merge_preserves_namespaced_offers_and_exact_category() -> None:
    # Given
    offers = (
        offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "C-1"),
        offer(Operation.GET_UNIT_CONTRACT_PRODUCT_INFO, "C-1"),
        offer(Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO, "C-1"),
    )

    # When
    products = merge_products(offers, ())

    # Then
    assert len(products) == 1
    assert products[0].category_key == ("46171622", "4617162201")
    assert tuple(item.namespaced_key for item in products[0].offers) == (
        (Operation.GET_MAS_CONTRACT_PRODUCT_INFO.value, "C-1"),
        (Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO.value, "C-1"),
        (Operation.GET_UNIT_CONTRACT_PRODUCT_INFO.value, "C-1"),
    )


def test_display_conflict_uses_latest_timestamp_then_operation_id_ascending() -> None:
    # Given
    offers = (
        offer(
            Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
            "B",
            OfferOverride(name="후순위명", updated_at="2026-07-16T00:00:00Z"),
        ),
        offer(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            "A",
            OfferOverride(name="선택명", updated_at="2026-07-16T00:00:00Z"),
        ),
    )

    # When
    product = merge_products(offers, ())[0]

    # Then
    assert product.product_name_raw == "선택명"
    assert product.product_name_key == "선택명"


def test_only_matching_registration_cancel_changes_offer_activity() -> None:
    # Given
    offers = (
        offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "A"),
        offer(Operation.GET_UNIT_CONTRACT_PRODUCT_INFO, "B"),
    )
    cancellations = (
        RegistrationCancellation(
            product_id="OTHER",
            target_operation=Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
            offer_key="B",
        ),
        RegistrationCancellation(
            product_id="P-1",
            target_operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            offer_key="A",
        ),
    )

    # When
    product = merge_products(offers, cancellations)[0]

    # Then
    assert tuple(item.active for item in product.offers) == (False, True)
    assert product.active is True
