"""Merge operation-scoped catalog offers into canonical products."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.quota import Operation
from g2b_compare.normalize.text import normalize_text

if TYPE_CHECKING:
    from collections.abc import Callable

OFFER_OPERATIONS: Final = frozenset(tuple(Operation)[:3])
type NamespacedOfferKey = tuple[str, str]
type CategoryKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class SourceOffer:
    """One active-slice offer with raw provider provenance."""

    operation: Operation
    offer_key: str
    product_id: str
    category_no: str
    detail_category_no: str
    product_name_raw: str
    spec_name: str
    detail: str
    characteristic: str
    contract_price_raw: str
    unit_raw: str
    product_unit_price_raw: str
    active: bool
    source_updated_at: str
    raw_fields_json: str


@dataclass(frozen=True, slots=True)
class RegistrationCancellation:
    """A registration event proven to target one exact offer identity."""

    product_id: str
    target_operation: Operation
    offer_key: str


@dataclass(frozen=True, slots=True)
class MaterializedOffer:
    """An operation-namespaced offer retained under one product."""

    operation: Operation
    offer_key: str
    product_id: str
    contract_price_raw: str
    unit_raw: str
    product_unit_price_raw: str
    active: bool
    source_updated_at: str
    raw_fields_json: str

    @property
    def namespaced_key(self) -> NamespacedOfferKey:
        """Keep provider identities collision-free across operations."""
        return self.operation.value, self.offer_key


@dataclass(frozen=True, slots=True)
class CanonicalProduct:
    """Deterministic display projection with every underlying offer."""

    product_id: str
    category_key: CategoryKey
    product_name_raw: str
    product_name_key: str
    spec_name: str
    detail: str
    characteristic: str
    active: bool
    data_as_of: str
    offers: tuple[MaterializedOffer, ...]


def merge_products(
    offers: tuple[SourceOffer, ...],
    cancellations: tuple[RegistrationCancellation, ...],
) -> tuple[CanonicalProduct, ...]:
    """Merge by product ID while applying only exact registration cancellations."""
    grouped: defaultdict[str, list[SourceOffer]] = defaultdict(list)
    for offer in offers:
        if offer.operation not in OFFER_OPERATIONS:
            continue
        grouped[offer.product_id].append(offer)
    cancellation_keys = frozenset(
        (item.product_id, item.target_operation, item.offer_key)
        for item in cancellations
    )
    return tuple(
        _merge_one(product_id, tuple(grouped[product_id]), cancellation_keys)
        for product_id in sorted(grouped)
    )


def _merge_one(
    product_id: str,
    sources: tuple[SourceOffer, ...],
    cancellation_keys: frozenset[tuple[str, Operation, str]],
) -> CanonicalProduct:
    ordered = tuple(
        sorted(sources, key=lambda item: (item.operation.value, item.offer_key))
    )
    offers = tuple(
        MaterializedOffer(
            operation=item.operation,
            offer_key=item.offer_key,
            product_id=item.product_id,
            contract_price_raw=item.contract_price_raw,
            unit_raw=item.unit_raw,
            product_unit_price_raw=item.product_unit_price_raw,
            active=item.active
            and (product_id, item.operation, item.offer_key) not in cancellation_keys,
            source_updated_at=item.source_updated_at,
            raw_fields_json=item.raw_fields_json,
        )
        for item in ordered
    )
    category = _display_category(ordered)
    name = _display_text(ordered, lambda item: item.product_name_raw)
    return CanonicalProduct(
        product_id=product_id,
        category_key=category,
        product_name_raw=name,
        product_name_key=normalize_text(name).derived,
        spec_name=_display_text(ordered, lambda item: item.spec_name),
        detail=_display_text(ordered, lambda item: item.detail),
        characteristic=_display_text(ordered, lambda item: item.characteristic),
        active=any(item.active for item in offers),
        data_as_of=max(item.source_updated_at for item in ordered),
        offers=offers,
    )


def _precedence(sources: tuple[SourceOffer, ...]) -> tuple[SourceOffer, ...]:
    timestamps = sorted({item.source_updated_at for item in sources}, reverse=True)
    return tuple(
        item
        for timestamp in timestamps
        for item in sorted(
            (
                candidate
                for candidate in sources
                if candidate.source_updated_at == timestamp
            ),
            key=lambda candidate: (candidate.operation.value, candidate.offer_key),
        )
    )


def _display_text(
    sources: tuple[SourceOffer, ...],
    select: Callable[[SourceOffer], str],
) -> str:
    for item in _precedence(sources):
        value = select(item)
        if value:
            return value
    return ""


def _display_category(sources: tuple[SourceOffer, ...]) -> CategoryKey:
    for item in _precedence(sources):
        if item.category_no:
            return item.category_no, item.detail_category_no
    return "", ""
