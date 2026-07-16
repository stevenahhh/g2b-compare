"""Materialize product attributes and expose exact collection coverage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

type FetchStatus = Literal[
    "complete-nonempty",
    "complete-empty",
    "pending",
    "failed",
    "expired-retained",
    "carried-forward",
]


@dataclass(frozen=True, slots=True)
class AttributeSourceRow:
    """One source attribute with raw and parsed representations."""

    attribute_key: str
    ordinal: int
    attribute_source_key: str
    raw_name: str
    raw_value: str
    canonical_value: str | None
    canonical_unit: str | None
    parse_status: str


@dataclass(frozen=True, slots=True)
class ProductAttribute:
    """One deterministically ordered materialized attribute."""

    attribute_key: str
    ordinal: int
    attribute_source_key: str
    raw_name: str
    raw_value: str
    canonical_value: str | None
    canonical_unit: str | None
    parse_status: str


@dataclass(frozen=True, slots=True)
class AttributeCoverageState:
    """Facts deciding whether one active product is currently covered."""

    product_id: str
    fetch_status: FetchStatus
    fingerprint_current: bool
    ttl_current: bool
    active: bool


@dataclass(frozen=True, slots=True)
class AttributeCoverage:
    """Exact current-product coverage numerator and denominator."""

    covered_count: int
    active_count: int
    ratio: str


def materialize_attributes(
    rows: tuple[AttributeSourceRow, ...],
) -> tuple[ProductAttribute, ...]:
    """Sort attributes by codepoint key and source ordinal while preserving raw."""
    return tuple(
        ProductAttribute(
            row.attribute_key,
            row.ordinal,
            row.attribute_source_key,
            row.raw_name,
            row.raw_value,
            row.canonical_value,
            row.canonical_unit,
            row.parse_status,
        )
        for row in sorted(
            rows,
            key=lambda item: (
                item.attribute_key,
                item.ordinal,
                item.attribute_source_key,
            ),
        )
    )


def attribute_coverage(
    states: tuple[AttributeCoverageState, ...],
) -> AttributeCoverage:
    """Count complete current states among all active products exactly once."""
    active = tuple(item for item in states if item.active)
    covered = sum(
        item.fetch_status in ("complete-nonempty", "complete-empty", "carried-forward")
        and item.fingerprint_current
        and item.ttl_current
        for item in active
    )
    denominator = len(active)
    ratio = Decimal(0) if denominator == 0 else Decimal(covered) / Decimal(denominator)
    return AttributeCoverage(covered, denominator, str(ratio.normalize()))
