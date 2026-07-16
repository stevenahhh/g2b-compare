"""Attribute page staging and completeness models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import TypeAdapter

from g2b_compare.contracts.redact import JsonScalar

type QuarantineReason = Literal[
    "missing-attribute-source-key",
    "wrong-product-id",
]
_ROW_ADAPTER: Final = TypeAdapter(dict[str, JsonScalar])


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    """One identity-complete live-observed attribute row."""

    product_id: str
    attribute_name: str
    source_ordinal: int
    source_key: str
    origin_page_id: int
    raw_fields_json: str
    payload_sha: str


@dataclass(frozen=True, slots=True)
class QuarantinedAttribute:
    """One row excluded from searchable attribute state."""

    reason: QuarantineReason
    raw_fields_json: str


@dataclass(frozen=True, slots=True)
class AttributePage:
    """One parsed provider page before completeness assembly."""

    product_id: str
    page_no: int
    page_size: int
    total_count: int
    records: tuple[AttributeRecord, ...]
    quarantined: tuple[QuarantinedAttribute, ...]
    official_no_data: bool


@dataclass(frozen=True, slots=True)
class CompleteAttributeCollection:
    """A fully staged product attribute collection."""

    product_id: str
    records: tuple[AttributeRecord, ...]
    official_no_data: bool


@dataclass(frozen=True, slots=True)
class IncompleteAttributeCollection:
    """A collection that must retain prior searchable rows."""

    reason: str


type AttributeCollection = CompleteAttributeCollection | IncompleteAttributeCollection


def assemble_pages(pages: tuple[AttributePage, ...]) -> AttributeCollection:
    """Assemble complete pages and assign product-global source ordinals."""
    if not pages:
        return IncompleteAttributeCollection("partial-pagination")
    ordered = tuple(sorted(pages, key=lambda page: page.page_no))
    first = ordered[0]
    incomplete_reason = _incomplete_reason(ordered, first)
    if incomplete_reason is not None:
        return IncompleteAttributeCollection(incomplete_reason)
    if first.total_count == 0:
        return CompleteAttributeCollection(
            first.product_id,
            (),
            official_no_data=True,
        )
    source_rows = tuple(record for page in ordered for record in page.records)
    occurrences: dict[str, int] = {}
    records: list[AttributeRecord] = []
    for record in source_rows:
        ordinal = occurrences.get(record.attribute_name, 0)
        occurrences[record.attribute_name] = ordinal + 1
        raw = _ROW_ADAPTER.validate_json(record.raw_fields_json)
        raw["source_ordinal"] = ordinal
        records.append(
            AttributeRecord(
                record.product_id,
                record.attribute_name,
                ordinal,
                json.dumps(
                    [record.product_id, record.attribute_name, ordinal],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                record.origin_page_id,
                encode_attribute_row(raw),
                record.payload_sha,
            )
        )
    return CompleteAttributeCollection(
        first.product_id,
        tuple(records),
        official_no_data=False,
    )


def _incomplete_reason(
    ordered: tuple[AttributePage, ...], first: AttributePage
) -> str | None:
    page_numbers = tuple(page.page_no for page in ordered)
    expected_pages = max(
        1, (first.total_count + first.page_size - 1) // first.page_size
    )
    invalid = (
        any(page.product_id != first.product_id for page in ordered)
        or any(page.page_size != first.page_size for page in ordered)
        or any(page.total_count != first.total_count for page in ordered)
        or any(page.quarantined for page in ordered)
    )
    source_rows = tuple(record for page in ordered for record in page.records)
    signatures = tuple(
        tuple(record.raw_fields_json for record in page.records) for page in ordered
    )
    repeated = any(
        signature and signatures.count(signature) > 1 for signature in signatures
    )
    reason: str | None = None
    if len(page_numbers) != len(set(page_numbers)):
        reason = "duplicate-page"
    elif page_numbers != tuple(range(1, expected_pages + 1)):
        reason = "missing-page"
    elif invalid:
        reason = "inconsistent-page"
    elif first.total_count == 0 and not (len(ordered) == 1 and first.official_no_data):
        reason = "no-data-not-complete-empty"
    elif repeated:
        reason = "repeated-page"
    elif len(source_rows) != first.total_count:
        reason = "inconsistent-count"
    return reason


def encode_attribute_row(row: dict[str, JsonScalar]) -> str:
    """Serialize one live-observed row canonically."""
    return json.dumps(
        row,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
