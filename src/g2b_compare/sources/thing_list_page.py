"""Typed attribute page construction after wire parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, final, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from g2b_compare.sources.thing_list_models import (
    AttributePage,
    AttributeRecord,
    QuarantinedAttribute,
    encode_attribute_row,
)

if TYPE_CHECKING:
    from g2b_compare.contracts.wire import ObservedPage
    from g2b_compare.sources.thing_list_response import AttributePageMetadata

_MALFORMED_ITEM: Final = "malformed-item"
_PAGE_METADATA_MISMATCH: Final = "page-metadata-mismatch"
_PAGE_ITEM_COUNT_MISMATCH: Final = "page-item-count-mismatch"
_NO_DATA_INCOMPLETE: Final = "no-data-not-complete-empty"


@final
class AttributePageBuildError(Exception):
    """Reject provider page content before searchable state construction."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one sanitized page reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class AttributePageExpectation:
    """Trusted request and manifest facts checked against a provider page."""

    product_id: str
    page_no: int
    page_size: int
    required_fields: tuple[str, ...]


class _AttributeIdentity(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore", frozen=True, strict=True
    )

    product_id: str = Field(alias="prdctIdntNo", min_length=1)
    attribute_name: str = Field(alias="attrNm", min_length=1)
    source_ordinal: int = Field(ge=0)


def build_attribute_page(
    expected: AttributePageExpectation,
    observed: ObservedPage,
    metadata: AttributePageMetadata,
    origin_page_id: int,
) -> AttributePage:
    """Build one page only from provider-reported pagination metadata."""
    if (
        metadata.page_no != expected.page_no
        or metadata.page_size != expected.page_size
        or observed.reported_page_size != metadata.page_size
        or observed.total_count != metadata.total_count
    ):
        raise AttributePageBuildError(_PAGE_METADATA_MISMATCH)
    if not observed.rows:
        if metadata.total_count != 0:
            raise AttributePageBuildError(_NO_DATA_INCOMPLETE)
        return AttributePage(
            expected.product_id,
            metadata.page_no,
            metadata.page_size,
            0,
            (),
            (),
            official_no_data=True,
        )
    first_item = (metadata.page_no - 1) * metadata.page_size
    remaining = max(0, metadata.total_count - first_item)
    if len(observed.rows) != min(metadata.page_size, remaining):
        raise AttributePageBuildError(_PAGE_ITEM_COUNT_MISMATCH)
    if any(tuple(sorted(row)) != expected.required_fields for row in observed.rows):
        raise AttributePageBuildError(_MALFORMED_ITEM)
    records: list[AttributeRecord] = []
    quarantined: list[QuarantinedAttribute] = []
    for row in observed.rows:
        encoded = encode_attribute_row(row)
        try:
            identity = _AttributeIdentity.model_validate(row)
        except ValidationError:
            quarantined.append(
                QuarantinedAttribute("missing-attribute-source-key", encoded)
            )
            continue
        if identity.product_id != expected.product_id:
            quarantined.append(QuarantinedAttribute("wrong-product-id", encoded))
            continue
        key = json.dumps(
            [identity.product_id, identity.attribute_name, identity.source_ordinal],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        records.append(
            AttributeRecord(
                identity.product_id,
                identity.attribute_name,
                identity.source_ordinal,
                key,
                origin_page_id,
                encoded,
                observed.payload_sha256,
            )
        )
    return AttributePage(
        expected.product_id,
        metadata.page_no,
        metadata.page_size,
        metadata.total_count,
        tuple(records),
        tuple(quarantined),
        official_no_data=False,
    )
