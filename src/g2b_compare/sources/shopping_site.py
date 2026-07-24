"""Typed access to the public Shopping Mall company search."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final, Protocol, final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.redact import JsonValue
from g2b_compare.sources.shopping_mall import (
    CatalogPage,
    CatalogRecord,
    QuarantinedRecord,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)
from g2b_compare.sources.transport import RetryableTransportError

SITE_OPERATION: Final = Operation.GET_SHOPPING_MALL_PRODUCT_INFO
SITE_SEARCH_URL: Final = (
    "https://shop.g2b.go.kr/gm/gms/gmsd/newShopUntySrchApi.do"
)
SITE_HOME: Final = "https://shop.g2b.go.kr"
PAGE_SIZE: Final = 100
REQUEST_FAILURE: Final = "shopping-site-request"
RESPONSE_FAILURE: Final = "shopping-site-response"
type SiteRow = dict[str, JsonValue]


class _SiteEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    rows: tuple[SiteRow, ...] = Field(alias="rsltList")
    total_count: int = Field(alias="totalSize")
    error_code: int = Field(alias="ErrorCode")


@dataclass(frozen=True, slots=True)
class ShoppingSitePage:
    """One public site result page before catalog normalization."""

    rows: tuple[SiteRow, ...]
    page_number: int
    total_count: int


class ShoppingSiteAdapter(Protocol):
    """Public site capability consumed by the company crawler."""

    def fetch(self, company_name: str, page_number: int) -> ShoppingSitePage:
        """Fetch one company result page."""
        ...


@final
@dataclass(frozen=True, slots=True)
class HttpShoppingSiteAdapter:
    """HTTP adapter for the public, keyless Shopping Mall search."""

    client: httpx.Client

    def fetch(self, company_name: str, page_number: int) -> ShoppingSitePage:
        """Fetch one 100-row site page."""
        try:
            response = self.client.post(
                SITE_SEARCH_URL,
                headers=_headers(),
                json={"searchVO": _search(company_name, page_number)},
            )
            _ = response.raise_for_status()
            envelope = _SiteEnvelope.model_validate_json(response.content)
        except (httpx.HTTPError, ValueError) as error:
            raise RetryableTransportError(REQUEST_FAILURE, attempts=1) from error
        if envelope.error_code != 0:
            raise RetryableTransportError(RESPONSE_FAILURE, attempts=1)
        return ShoppingSitePage(envelope.rows, page_number, envelope.total_count)


def catalog_page(page: ShoppingSitePage) -> tuple[CatalogPage, datetime]:
    """Normalize a site page into the existing catalog boundary."""
    observed_at = datetime.now(UTC)
    records: list[CatalogRecord] = []
    rejected: list[QuarantinedRecord] = []
    for row in page.rows:
        contract_item = site_text(row, "ctrtItemMngNo")
        product_id = site_text(row, "itemIdnfNo")
        if not contract_item or not product_id:
            rejected.append(QuarantinedRecord("missing-site-identity", row))
        else:
            records.append(_record(row, contract_item, product_id, observed_at))
    fingerprint = hashlib.sha256(
        f"shopping-site|{page.page_number}|{page.total_count}".encode()
    ).hexdigest()
    raw = json.dumps(page.rows, ensure_ascii=False, separators=(",", ":")).encode()
    return (
        CatalogPage(
            operation=SITE_OPERATION,
            records=tuple(records),
            quarantined=tuple(rejected),
            page_number=page.page_number,
            page_size=PAGE_SIZE,
            total_count=page.total_count,
            request_fingerprint=fingerprint,
            raw_response=raw,
            content_type="application/json",
        ),
        observed_at,
    )


def _record(
    row: SiteRow, contract_item: str, product_id: str, observed_at: datetime
) -> CatalogRecord:
    fields: SiteRow = {
        **row,
        "cntrctCorpNm": site_text(row, "crawlCompanyName"),
        "prdctUnit": site_text(row, "ctrtUntVal"),
        "cntrctMthdNm": site_text(row, "shopCtrtTyNm"),
        "prdctDlvryCndtnNm": site_text(row, "devyCndtNm"),
        "dlvrTmlmtDaynum": site_text(row, "dlvgdsTermNody"),
        "cntrctEndDate": site_text(row, "ctrtEndYmd"),
    }
    registered = site_text(row, "ctrtYmd")
    image_path = site_text(row, "sImgSrc")
    return CatalogRecord(
        identity=SourceIdentity(
            SITE_OPERATION,
            (contract_item, site_text(row, "ctrtItemSqno") or "0"),
        ),
        product_id=product_id,
        classification_number=site_text(row, "itemClsfNo"),
        category_name=site_text(row, "itemCfnm"),
        detail_category_number=site_text(row, "dtlsPrnmNo"),
        spec_name=site_text(row, "itemIdnfNm"),
        contract_price=site_text(row, "ctrtUprc"),
        image_url=f"{SITE_HOME}{image_path}" if image_path else "",
        timestamp=TimestampEvidence(
            registered or observed_at.isoformat(),
            TimestampOrigin.PROVIDER_REGISTERED
            if registered
            else TimestampOrigin.OBSERVED_AT_FALLBACK,
            int(bool(registered)),
        ),
        raw_fields=fields,
    )


def _search(company_name: str, page_number: int) -> dict[str, JsonValue]:
    return {
        "selectValue": "etpsNm",
        "searchKeyword": company_name,
        "target": "계300001,계300002,계309999",
        "prchsMthdSeCd": "본010001",
        "recordCountPerPage": str(PAGE_SIZE),
        "currentPage": page_number,
        "sortCndt": "SRCH_UPRC_ASC",
        "dgtlSrvcMallYn": "N",
    }


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=UTF-8",
        "Menu-Info": (
            '{"menuNo":"12167","menuCangVal":"GMSD003_01",'
            '"bsneClsfCd":"%EC%97%85130034","scrnNo":"07677"}'
        ),
        "Referer": f"{SITE_HOME}/",
        "Usr-Id": "null",
        "submissionid": (
            "mf_wfm_container_tabShopSubHeader_contents_"
            "tabShopLstFormCon_body_sbmSrch"
        ),
    }


def site_text(row: SiteRow, key: str) -> str:
    """Return one HTML-unescaped site scalar."""
    value = row.get(key)
    return html.unescape("" if value is None else str(value)).strip()
