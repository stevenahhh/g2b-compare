"""Strict G2B transport and JSON envelope boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, override

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from g2b_compare.config import G2B_API_BASE_URL, G2B_ATTRIBUTE_API_BASE_URL
from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.redact import JsonScalar  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

PRODUCT_IDS: Final = ("22065235", "22065237", "22066417")
CONTRACT_OPERATIONS: Final = frozenset(tuple(Operation)[:3])
CONTRACT_KEYS: Final = ("shopngCntrctNo", "shopngCntrctSno")
DELIVERY_KEYS: Final = ("dlvrReqNo", "dlvrReqChgOrd", "prdctSno")
ATTRIBUTE_KEYS: Final = ("prdctIdntNo", "attrNm", "source_ordinal")
MALFORMED_ENVELOPE: Final = "malformed-envelope"
ATTRIBUTE_HTTP_ONLY: Final = "attribute-http-only"


class ResponseLike(Protocol):
    """Response fields consumed by contract capture."""

    @property
    def status_code(self) -> int:
        """Return the received HTTP status."""
        ...

    @property
    def headers(self) -> Mapping[str, str]:
        """Return case-insensitive response headers."""
        ...

    @property
    def content(self) -> bytes:
        """Return the unparsed response body."""
        ...


class Requester(Protocol):
    """No-redirect request capability used by contract capture."""

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> ResponseLike:
        """Send one request with runtime-only parameters."""
        ...


@dataclass(frozen=True, slots=True)
class HttpxRequester:
    """Strict no-redirect HTTP adapter with bounded split timeouts."""

    client: httpx.Client

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> httpx.Response:
        """Send one bounded request without following a redirect."""
        return self.client.get(
            url,
            params=params,
            follow_redirects=follow_redirects,
            timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10),
        )


@dataclass(frozen=True, slots=True)
class WireContractError(Exception):
    """Sanitized strict-wire rejection."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class ObservedPage:
    """Parsed non-secret page facts used by the state machine."""

    rows: tuple[dict[str, JsonScalar], ...]
    fields: tuple[str, ...]
    reported_page_size: int | None
    total_count: int
    payload_sha256: str


class _ApiHeader(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    result_code: str = Field(alias="resultCode")
    result_message: str = Field(alias="resultMsg")


class _ApiItems(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    item: tuple[dict[str, JsonScalar], ...] | dict[str, JsonScalar]


class _ApiBody(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    items: _ApiItems | tuple[dict[str, JsonScalar], ...] | str
    num_of_rows: int | None = Field(default=None, alias="numOfRows")
    page_no: int = Field(alias="pageNo")
    total_count: int = Field(alias="totalCount")


class _ApiResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    header: _ApiHeader
    body: _ApiBody


class _ApiEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    response: _ApiResponse


def parse_page(content: bytes, operation: Operation) -> ObservedPage:
    """Parse strict success envelopes and retain schema facts."""
    try:
        envelope = _ApiEnvelope.model_validate_json(content)
    except ValidationError:
        raise WireContractError(MALFORMED_ENVELOPE) from None
    body = envelope.response.body
    if envelope.response.header.result_code != "00":
        raise WireContractError(MALFORMED_ENVELOPE)
    rows = _rows_from_items(body.items)
    if rows and any(set(row) != set(rows[0]) for row in rows[1:]):
        raise WireContractError(MALFORMED_ENVELOPE)
    if operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE:
        rows = _attribute_rows(rows)
    fields = tuple(sorted(rows[0])) if rows else ()
    return ObservedPage(
        rows=rows,
        fields=fields,
        reported_page_size=body.num_of_rows,
        total_count=body.total_count,
        payload_sha256=hashlib.sha256(content).hexdigest(),
    )


def _attribute_rows(
    rows: tuple[dict[str, JsonScalar], ...],
) -> tuple[dict[str, JsonScalar], ...]:
    ordered = sorted(
        rows,
        key=lambda row: json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    occurrences: dict[tuple[JsonScalar, JsonScalar], int] = {}
    result: list[dict[str, JsonScalar]] = []
    for row in ordered:
        identity = (row.get("prdctIdntNo"), row.get("attrNm"))
        ordinal = occurrences.get(identity, 0)
        occurrences[identity] = ordinal + 1
        result.append({**row, "source_ordinal": ordinal})
    return tuple(result)


def _rows_from_items(
    items: _ApiItems | tuple[dict[str, JsonScalar], ...] | str,
) -> tuple[dict[str, JsonScalar], ...]:
    if isinstance(items, _ApiItems):
        return _rows_from_wrapped(items.item)
    if isinstance(items, tuple):
        return items
    return ()


def _rows_from_wrapped(
    items: tuple[dict[str, JsonScalar], ...] | dict[str, JsonScalar],
) -> tuple[dict[str, JsonScalar], ...]:
    if isinstance(items, dict):
        return (items,)
    return items


def official_url(operation: Operation) -> str:
    """Resolve one immutable official HTTPS operation URL."""
    base = (
        G2B_ATTRIBUTE_API_BASE_URL
        if operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
        else G2B_API_BASE_URL
    )
    url = f"{base}/{operation}"
    if not url.startswith("https://apis.data.go.kr/1230000/"):
        raise WireContractError(ATTRIBUTE_HTTP_ONLY)
    return url


def candidates(
    operation: Operation,
    today: date,
) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Build the three bounded discovery candidates for an operation."""
    base = (("type", "json"), ("pageNo", "1"), ("numOfRows", "1"))
    if operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE:
        return tuple((*base, ("prdctIdntNo", product_id)) for product_id in PRODUCT_IDS)
    if operation in CONTRACT_OPERATIONS:
        day = _timestamp_range(today, today)
        month = _timestamp_range(today - timedelta(days=30), today)
        return (
            (*base, ("prdctIdntNo", PRODUCT_IDS[0]), *day),
            (*base, ("prdctIdntNo", PRODUCT_IDS[0]), *month),
            (*base, *day),
        )
    end = today - timedelta(days=1)
    spans = (0, 30, 364)
    if operation in {
        Operation.GET_DELIVERY_REQUEST_DETAIL,
        Operation.GET_SHOPPING_MALL_PRODUCT_INFO,
    }:
        return tuple(
            (*base, ("inqryDiv", "1"), *_date_range(end - timedelta(days=days), end))
            for days in spans
        )
    return tuple(
        (*base, *_timestamp_range(end - timedelta(days=days), end)) for days in spans
    )


def page_size(
    params: tuple[tuple[str, str], ...], size: int
) -> tuple[tuple[str, str], ...]:
    """Replace only the allowlisted page-size parameter."""
    return tuple(
        (key, str(size) if key == "numOfRows" else value) for key, value in params
    )


def stable_keys(operation: Operation) -> tuple[str, ...]:
    """Return the proven identity fields for one operation family."""
    if operation is Operation.GET_DELIVERY_REQUEST_DETAIL:
        return DELIVERY_KEYS
    if operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE:
        return ATTRIBUTE_KEYS
    return CONTRACT_KEYS


def _timestamp_range(start: date, end: date) -> tuple[tuple[str, str], ...]:
    return (
        ("rgstDtBgnDt", start.strftime("%Y%m%d0000")),
        ("rgstDtEndDt", end.strftime("%Y%m%d2359")),
    )


def _date_range(start: date, end: date) -> tuple[tuple[str, str], ...]:
    return (
        ("inqryBgnDate", start.strftime("%Y%m%d")),
        ("inqryEndDate", end.strftime("%Y%m%d")),
    )
