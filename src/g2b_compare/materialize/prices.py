"""Derive comparable current catalog prices without imputation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.normalize.text import normalize_text

if TYPE_CHECKING:
    from .products import MaterializedOffer, NamespacedOfferKey


@dataclass(frozen=True, slots=True)
class ComparisonPrice:
    """Comparable price or an explicit reason it is inactive."""

    active: bool
    amount_won: int | None
    unit_key: str | None
    offer_key: NamespacedOfferKey | None
    reason: str | None


def comparison_price(offers: tuple[MaterializedOffer, ...]) -> ComparisonPrice:
    """Select the minimum active positive contract price for one unit basis."""
    active = tuple(item for item in offers if item.active)
    if not active:
        return _inactive("no-active-offer")
    parsed: list[tuple[int, str, MaterializedOffer]] = []
    for offer in active:
        price, reason = _parse_price(offer.contract_price_raw)
        if reason is not None:
            return _inactive(reason)
        unit_key = normalize_text(offer.unit_raw).derived
        if not unit_key:
            return _inactive("missing-unit")
        if price is not None:
            parsed.append((price, unit_key, offer))
    units = {item[1] for item in parsed}
    if len(units) != 1:
        return _inactive("mixed-unit")
    selected = min(parsed, key=lambda item: (item[0], item[2].namespaced_key))
    return ComparisonPrice(
        active=True,
        amount_won=selected[0],
        unit_key=selected[1],
        offer_key=selected[2].namespaced_key,
        reason=None,
    )


def _parse_price(raw: str) -> tuple[int | None, str | None]:
    candidate = raw.replace(",", "").strip()
    if not candidate:
        return None, "missing-price"
    try:
        value = int(candidate)
    except ValueError:
        return None, "missing-price"
    if value < 0:
        return None, "negative-price"
    if value == 0:
        return None, "zero-price"
    return value, None


def _inactive(reason: str) -> ComparisonPrice:
    return ComparisonPrice(
        active=False,
        amount_won=None,
        unit_key=None,
        offer_key=None,
        reason=reason,
    )
