"""Concurrent company collection and reconciliation for Shopping Mall rows."""

from __future__ import annotations

import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, ClassVar, cast

from pydantic import BaseModel, ConfigDict

from g2b_compare.company_product_crawl import CompanyProductCrawlResult
from g2b_compare.sources.shopping_site import (
    PAGE_SIZE,
    SITE_OPERATION,
    ShoppingSiteAdapter,
    ShoppingSitePage,
    SiteRow,
    catalog_page,
    site_text,
)
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.priority_models import CrawlTarget
    from g2b_compare.priority_store import PriorityStore


class SiteCompanyCrawlReport(BaseModel):
    """Current site row and unique-product counts for one company."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    company_name: str
    declared_product_count: int
    provider_row_count: int
    accepted_row_count: int
    quarantined_row_count: int
    unique_offer_count: int
    unique_product_count: int
    pending: bool
    provider_mismatch: int
    declared_product_delta: int


@dataclass(frozen=True, slots=True)
class _CompanyPages:
    target: CrawlTarget
    pages: tuple[ShoppingSitePage, ...]
    calls: int
    failure_reason: str = ""


def crawl_company_site_products(
    store: PriorityStore,
    adapter: ShoppingSiteAdapter,
    *,
    workers: int = 8,
) -> CompanyProductCrawlResult:
    """Collect every current main-product offer for every priority company."""
    targets = store.crawl_targets((SITE_OPERATION,))
    accepted = 0
    quarantined = 0
    calls = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_fetch_company, adapter, target): target
            for target in targets
        }
        for future in as_completed(futures):
            result = future.result()
            calls += result.calls
            if result.failure_reason:
                failures.append(result.failure_reason)
                continue
            for site_page in result.pages:
                page, observed_at = catalog_page(site_page)
                accepted += len(page.records)
                quarantined += len(page.quarantined)
                store.save_catalog_page(
                    company_name=result.target.company_name,
                    operation=SITE_OPERATION,
                    page_number=page.page_number,
                    page_size=PAGE_SIZE,
                    total_count=page.total_count,
                    records=page.records,
                    observed_at=observed_at,
                    quarantined=page.quarantined,
                    request_fingerprint=page.request_fingerprint,
                )
    return CompanyProductCrawlResult(
        calls=calls,
        accepted_rows=accepted,
        quarantined_rows=quarantined,
        failures=len(failures),
        failure_reasons=tuple(failures),
        remaining_targets=len(store.crawl_targets((SITE_OPERATION,))),
    )


def read_company_site_crawl_report(
    database: Path,
) -> tuple[SiteCompanyCrawlReport, ...]:
    """Reconcile public site rows, stored offers, and unique main products."""
    operation = str(SITE_OPERATION)
    query = """
        WITH pages AS (
            SELECT company_name, MAX(provider_total_count) AS provider_count,
                   SUM(accepted_count) AS accepted_count,
                   SUM(quarantined_count) AS quarantined_count
            FROM priority_company_crawl_pages
            WHERE operation = ? GROUP BY company_name
        ), offers AS (
            SELECT company_name, COUNT(*) AS offer_count,
                   COUNT(DISTINCT product_id) AS product_count
            FROM priority_product_offers
            WHERE active = 1 AND operation = ? GROUP BY company_name
        ), completed AS (
            SELECT company_name, complete FROM priority_crawl_state
            WHERE operation = ?
        )
        SELECT company.name, company.declared_product_count,
               COALESCE(pages.provider_count, 0),
               COALESCE(pages.accepted_count, 0),
               COALESCE(pages.quarantined_count, 0),
               COALESCE(offers.offer_count, 0),
               COALESCE(offers.product_count, 0),
               COALESCE(completed.complete, 0)
        FROM priority_companies AS company
        LEFT JOIN pages ON pages.company_name = company.name
        LEFT JOIN offers ON offers.company_name = company.name
        LEFT JOIN completed ON completed.company_name = company.name
        ORDER BY company.source_row
    """
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(query, (operation,) * 3).fetchall(),
        )
    return tuple(_report(row) for row in rows)


def _fetch_company(
    adapter: ShoppingSiteAdapter, target: CrawlTarget
) -> _CompanyPages:
    raw_pages: list[ShoppingSitePage] = []
    try:
        first = adapter.fetch(target.company_name, 1)
        raw_pages.append(first)
        raw_pages.extend(
            adapter.fetch(target.company_name, page_number)
            for page_number in range(2, max(1, ceil(first.total_count / PAGE_SIZE)) + 1)
        )
    except RetryableTransportError as error:
        return _CompanyPages(target, (), len(raw_pages) + 1, error.reason)
    candidate_rows = tuple(
        row
        for page in raw_pages
        for row in page.rows
        if _company_key(site_text(row, "ctentUntyGrpNm"))
        == _company_key(target.company_name)
    )
    businesses = {_business_key(row) for row in candidate_rows}
    location_businesses = {
        _business_key(row)
        for row in candidate_rows
        if _location_matches(row, target.location)
    }
    accepted_businesses = location_businesses or businesses
    rows = tuple(
        {**row, "crawlCompanyName": target.company_name}
        for row in candidate_rows
        if _business_key(row) in accepted_businesses
        and (location_businesses or len(businesses) == 1)
    )
    pages = tuple(
        ShoppingSitePage(
            rows=rows[offset : offset + PAGE_SIZE],
            page_number=(offset // PAGE_SIZE) + 1,
            total_count=len(rows),
        )
        for offset in range(0, max(1, len(rows)), PAGE_SIZE)
    )
    return _CompanyPages(target, pages, len(raw_pages))


def _report(row: tuple[object, ...]) -> SiteCompanyCrawlReport:
    declared = _integer(row[1])
    provider = _integer(row[2])
    quarantined = _integer(row[4])
    offers = _integer(row[5])
    products = _integer(row[6])
    return SiteCompanyCrawlReport(
        company_name=str(row[0]),
        declared_product_count=declared,
        provider_row_count=provider,
        accepted_row_count=_integer(row[3]),
        quarantined_row_count=quarantined,
        unique_offer_count=offers,
        unique_product_count=products,
        pending=not bool(row[7]),
        provider_mismatch=abs(provider - offers - quarantined),
        declared_product_delta=products - declared,
    )


def _integer(value: object) -> int:
    return value if isinstance(value, int) else int(str(value))


def _company_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("(주)", "주식회사")
    return "".join(character for character in normalized if character.isalnum())


def _business_key(row: SiteRow) -> str:
    return site_text(row, "bzmnRegNo") or site_text(row, "ctentUntyGrpNo")


def _location_matches(row: SiteRow, target_location: str) -> bool:
    target_key = _company_key(target_location)
    return any(
        target_key in _company_key(site_text(row, field))
        for field in ("addr", "hdofcLctnNm", "hdofcSgnguNm")
    )
