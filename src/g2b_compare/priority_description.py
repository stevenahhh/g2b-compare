"""Typed product-detail capture and HTML normalization contracts."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from typing import TYPE_CHECKING, ClassVar, Final, Literal, final, override
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from g2b_compare.db.models import RawBlobReceipt

BLOCK_TAGS: Final = frozenset(
    {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
SUPPRESSED_TAGS: Final = frozenset({"noscript", "script", "style"})
PARSER_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class ProductDetailTarget:
    """One collected main product eligible for live detail enrichment."""

    product_id: str
    contract_item_management_number: str
    source_url: str

    @classmethod
    def from_product(cls, product_id: str, source_url: str) -> ProductDetailTarget:
        """Parse the stable contract-item key from a collected detail URL."""
        values = parse_qs(urlparse(source_url).query).get("ctrtItemMngNo", ())
        if len(values) != 1 or not values[0]:
            raise ValueError(product_id)
        return cls(product_id, values[0], source_url)


@dataclass(frozen=True, slots=True)
class ProductDetailContent:
    """Decoded provider HTML and its normalized searchable text."""

    decoded_html: str
    detail_text: str
    detail_html_sha256: str
    parser_version: int = PARSER_VERSION


@dataclass(frozen=True, slots=True)
class ProductDetailObservation:
    """One append-only outcome from the live product-description boundary."""

    target: ProductDetailTarget
    endpoint_url: str
    request_fingerprint: str
    outcome: Literal["stored", "missing", "failed"]
    observed_at: str
    response_receipt: RawBlobReceipt | None
    content: ProductDetailContent | None
    http_status: int | None
    error_code: str | None


@final
class ProductDetailResponseError(Exception):
    """A stable secret-safe failure at the live detail boundary."""

    code: str

    def __init__(self, code: str) -> None:
        """Initialize one provider response failure."""
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code


class _DetailBody(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    product_id: str = Field(default="", alias="itemIdnfNo")
    escaped_html: str = Field(default="", alias="bulkItemDtlDscr")


class _DetailResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    error_code: int | str = Field(alias="ErrorCode")
    detail: _DetailBody | None = Field(alias="dlGdsDtlInfoMngM")


def parse_detail_response(
    target: ProductDetailTarget,
    payload: object,
) -> ProductDetailContent | None:
    """Parse one untrusted G2B detail response into deterministic content."""
    response = _DetailResponse.model_validate(payload)
    if str(response.error_code) != "0":
        reason = "provider_error"
        raise ProductDetailResponseError(reason)
    if response.detail is None:
        return None
    if not response.detail.escaped_html.strip():
        return None
    if response.detail.product_id not in {"", target.product_id}:
        reason = "product_mismatch"
        raise ProductDetailResponseError(reason)
    decoded_html = html.unescape(response.detail.escaped_html)
    detail_text = detail_text_from_html(decoded_html)
    if not detail_text:
        return None
    return ProductDetailContent(
        decoded_html=decoded_html,
        detail_text=detail_text,
        detail_html_sha256=sha256(decoded_html.encode()).hexdigest(),
    )


def detail_text_from_html(source_html: str) -> str:
    """Extract readable Korean detail text without image or style content."""
    parser = _DetailTextParser()
    parser.feed(source_html)
    parser.close()
    return "\n".join(
        line
        for raw_line in "".join(parser.parts).replace("\xa0", " ").splitlines()
        if (line := " ".join(raw_line.split()))
    )


@final
class _DetailTextParser(HTMLParser):
    parts: list[str]
    _suppressed_depth: int

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._suppressed_depth = 0

    @override
    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        _ = attrs
        if tag in SUPPRESSED_TAGS:
            self._suppressed_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in SUPPRESSED_TAGS:
            self._suppressed_depth = max(0, self._suppressed_depth - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    @override
    def handle_data(self, data: str) -> None:
        if self._suppressed_depth == 0:
            self.parts.append(re.sub(r"[\r\t]+", " ", data))
