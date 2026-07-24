"""Typed adapters for the four observed shopping-mall catalog operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import singledispatch
from typing import TYPE_CHECKING, Final, override

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.redact import JsonValue
from g2b_compare.contracts.wire import official_url
from g2b_compare.sources.envelope import parse_envelope
from g2b_compare.sources.transport import HttpTransport, TransportRequest

if TYPE_CHECKING:
    from datetime import datetime

CATALOG_OPERATIONS: Final = frozenset(tuple(Operation)[:4])
STABLE_KEY_FIELDS: Final = ("shopngCntrctNo", "shopngCntrctSno")
type RawFields = dict[str, JsonValue]


class TimestampOrigin(StrEnum):
    """Provenance and conflict precedence for one source timestamp."""

    PROVIDER_CHANGED = "provider-changed"
    PROVIDER_REGISTERED = "provider-registered"
    OBSERVED_AT_FALLBACK = "observed-at-fallback"


@dataclass(frozen=True, slots=True)
class TimestampEvidence:
    """Timestamp value with its explicit source precedence."""

    value: str
    origin: TimestampOrigin
    precedence: int


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Operation-scoped live-observed provider identity."""

    operation: Operation
    stable_source_key: tuple[str, str]


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    """Searchable typed catalog fields plus lossless raw provenance."""

    identity: SourceIdentity
    product_id: str
    classification_number: str
    category_name: str
    detail_category_number: str
    spec_name: str
    contract_price: str
    image_url: str
    timestamp: TimestampEvidence
    raw_fields: RawFields


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    """A non-searchable provider row retained for diagnosis."""

    reason: str
    raw_fields: RawFields


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One page split into searchable and quarantined provider records."""

    operation: Operation
    records: tuple[CatalogRecord, ...]
    quarantined: tuple[QuarantinedRecord, ...]
    page_number: int
    page_size: int
    total_count: int
    request_fingerprint: str
    raw_response: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ShoppingMallRequest:
    """Keyless catalog request plus fallback observation time."""

    operation: Operation
    params: tuple[tuple[str, str], ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class UnsupportedCatalogOperationError(Exception):
    """An authorized service operation is not a catalog source."""

    operation: Operation

    @override
    def __str__(self) -> str:
        return f"operation is not a catalog source: {self.operation}"


@dataclass(frozen=True, slots=True)
class ShoppingMallAdapter:
    """Fetch and type one catalog page without persisting a credential."""

    transport: HttpTransport

    def fetch(
        self,
        request: ShoppingMallRequest,
        *,
        service_key: str,
    ) -> CatalogPage:
        """Fetch one page and quarantine rows without a stable identity."""
        if request.operation not in CATALOG_OPERATIONS:
            raise UnsupportedCatalogOperationError(request.operation)
        response = self.transport.get(
            TransportRequest(
                operation=request.operation,
                url=official_url(request.operation),
                params=request.params,
            ),
            service_key=service_key,
        )
        provider_page = parse_envelope(response.content, response.media_type)
        records: list[CatalogRecord] = []
        quarantined: list[QuarantinedRecord] = []
        for row in provider_page.rows:
            stable_key = tuple(_text(row, field) for field in STABLE_KEY_FIELDS)
            if any(not part for part in stable_key):
                quarantined.append(QuarantinedRecord("missing-stable-source-key", row))
                continue
            records.append(
                _record(
                    request,
                    (stable_key[0], stable_key[1]),
                    row,
                )
            )
        return CatalogPage(
            operation=request.operation,
            records=tuple(records),
            quarantined=tuple(quarantined),
            page_number=provider_page.page_number,
            page_size=provider_page.page_size,
            total_count=provider_page.total_count,
            request_fingerprint=response.request_fingerprint,
            raw_response=response.content,
            content_type=response.content_type,
        )


def _record(
    request: ShoppingMallRequest,
    stable_key: tuple[str, str],
    row: RawFields,
) -> CatalogRecord:
    return CatalogRecord(
        identity=SourceIdentity(request.operation, stable_key),
        product_id=_text(row, "prdctIdntNo"),
        classification_number=_text(row, "prdctClsfcNo"),
        category_name=_text(row, "prdctClsfcNoNm"),
        detail_category_number=_text(row, "dtilPrdctClsfcNo"),
        spec_name=_text(row, "prdctSpecNm"),
        contract_price=_text(row, "cntrctPrceAmt"),
        image_url=_text(row, "prdctImgUrl"),
        timestamp=_timestamp(row, request.observed_at),
        raw_fields=row,
    )


def _timestamp(row: RawFields, observed_at: datetime) -> TimestampEvidence:
    changed = _text(row, "chgDt")
    if changed:
        return TimestampEvidence(changed, TimestampOrigin.PROVIDER_CHANGED, 2)
    registered = _text(row, "rgstDt")
    if registered:
        return TimestampEvidence(registered, TimestampOrigin.PROVIDER_REGISTERED, 1)
    return TimestampEvidence(
        observed_at.isoformat(), TimestampOrigin.OBSERVED_AT_FALLBACK, 0
    )


def _text(row: RawFields, key: str) -> str:
    return _scalar_text(row.get(key))


@singledispatch
def _scalar_text(value: JsonValue) -> str:
    _ = value
    return ""


@_scalar_text.register(str)
def text_from_string(value: str) -> str:
    """Normalize provider strings without discarding their value."""
    return value.strip()


@_scalar_text.register(bool)
def text_from_bool(value: bool) -> str:
    """Normalize provider booleans deterministically."""
    return "true" if value else "false"


@_scalar_text.register(int)
@_scalar_text.register(float)
def text_from_number(value: float) -> str:
    """Normalize provider numeric scalars deterministically."""
    return str(value)
