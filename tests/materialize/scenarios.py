from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.quota import Operation
from g2b_compare.materialize.attributes import (
    AttributeCoverageState,
    AttributeSourceRow,
    attribute_coverage,
    materialize_attributes,
)
from g2b_compare.materialize.options import FallbackText, build_option_text
from g2b_compare.materialize.prices import comparison_price
from g2b_compare.materialize.products import RegistrationCancellation, merge_products

from .support import OfferOverride, offer

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class HappyObservation:
    product_count: int
    offer_count: int
    price_won: int | None
    coverage: str
    option_sha: str


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


def _option(
    rows: tuple[AttributeSourceRow, ...],
    fallbacks: FallbackText,
) -> FailureObservation:
    value = build_option_text(materialize_attributes(rows), fallbacks)
    return FailureObservation(type(value).__name__, value.text or "empty-option")


def run_happy() -> HappyObservation:
    offers = (
        offer(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            "A",
            OfferOverride(price="1200000"),
        ),
        offer(
            Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
            "B",
            OfferOverride(price="1100000"),
        ),
        offer(
            Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO,
            "C",
            OfferOverride(price="1300000"),
        ),
    )
    product = merge_products(offers, ())[0]
    price = comparison_price(product.offers)
    coverage = attribute_coverage(
        (
            AttributeCoverageState(
                "P-1",
                "complete-nonempty",
                fingerprint_current=True,
                ttl_current=True,
                active=True,
            ),
        )
    )
    option = build_option_text(
        materialize_attributes(
            (
                AttributeSourceRow("zoom", 0, "A-2", "줌", "4 배", None, None, "raw"),
                AttributeSourceRow(
                    "resolution",
                    1,
                    "A-1",
                    " 해상도 ",
                    " ８００만 화소 ",
                    None,
                    None,
                    "raw",
                ),
            )
        ),
        FallbackText(" \uff18MP ", "8MP", "방수"),
    )
    return HappyObservation(
        1,
        len(product.offers),
        price.amount_won,
        coverage.ratio,
        option.utf8_sha256,
    )


def _conflict_name() -> FailureObservation:
    updated = "2026-07-16T00:00:00Z"
    product = merge_products(
        (
            offer(
                Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
                "B",
                OfferOverride(name="후순위명", updated_at=updated),
            ),
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(name="선택명", updated_at=updated),
            ),
        ),
        (),
    )[0]
    return FailureObservation(
        type(product).__name__,
        f"latest-name={product.product_name_raw}",
    )


def _price_failure(raw_price: str, unit: str) -> FailureObservation:
    product = merge_products(
        (
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(price="1"),
            ),
            offer(
                Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
                "B",
                OfferOverride(price=raw_price, unit=unit),
            ),
        ),
        (),
    )[0]
    value = comparison_price(product.offers)
    return FailureObservation(type(value).__name__, f"inactive:{value.reason}")


def _partial_attribute() -> FailureObservation:
    value = attribute_coverage(
        (
            AttributeCoverageState(
                "A",
                "complete-nonempty",
                fingerprint_current=True,
                ttl_current=True,
                active=True,
            ),
            AttributeCoverageState(
                "B",
                "failed",
                fingerprint_current=True,
                ttl_current=True,
                active=True,
            ),
        )
    )
    return FailureObservation(
        type(value).__name__,
        f"coverage={value.covered_count}/{value.active_count}",
    )


def _option_sha() -> FailureObservation:
    value = build_option_text((), FallbackText("8MP", "", ""))
    return FailureObservation(type(value).__name__, f"sha={value.utf8_sha256}")


def _one_offer_removed() -> FailureObservation:
    product = merge_products(
        (
            offer(
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
                OfferOverride(active=False),
            ),
            offer(Operation.GET_UNIT_CONTRACT_PRODUCT_INFO, "B"),
        ),
        (),
    )[0]
    return FailureObservation(type(product).__name__, f"active={int(product.active)}")


def _unmatched_cancel() -> FailureObservation:
    product = merge_products(
        (offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "A"),),
        (
            RegistrationCancellation(
                "OTHER",
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                "A",
            ),
        ),
    )[0]
    return FailureObservation(type(product).__name__, f"active={int(product.active)}")


_SCENARIOS: Final[dict[str, Callable[[], FailureObservation]]] = {
    "conflict-name": _conflict_name,
    "missing-detail": partial(_option, (), FallbackText("8MP", "", "방수")),
    "zero-price": partial(_price_failure, "0", "대"),
    "negative-price": partial(_price_failure, "-1", "대"),
    "mixed-unit": partial(_price_failure, "2", "식"),
    "partial-attribute": _partial_attribute,
    "option-first-nonempty-fallback": partial(
        _option,
        (),
        FallbackText("", "세부", "특성"),
    ),
    "attribute-order": partial(
        _option,
        (
            AttributeSourceRow("z", 0, "2", "Z", "2", None, None, "raw"),
            AttributeSourceRow("a", 1, "1", "A", "1", None, None, "raw"),
        ),
        FallbackText("", "", ""),
    ),
    "segment-delimiter": partial(_option, (), FallbackText("사양", "상세", "")),
    "segment-duplicate": partial(
        _option,
        (
            AttributeSourceRow("a", 0, "1", "모델", "X", None, None, "raw"),
            AttributeSourceRow("a", 1, "2", "모델", " X ", None, None, "raw"),
        ),
        FallbackText("", "", ""),
    ),
    "all-empty-option": partial(_option, (), FallbackText("", "", "")),
    "option-byte-sha": _option_sha,
    "one-offer-removed": _one_offer_removed,
    "unmatched-registration-cancel": _unmatched_cancel,
}


def observe_failure(scenario: str) -> FailureObservation:
    return _SCENARIOS[scenario]()
