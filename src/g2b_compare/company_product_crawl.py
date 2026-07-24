"""Exact, resumable collection of main products for priority companies."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, cast

from pydantic import BaseModel, ConfigDict

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.shopping_mall import ShoppingMallRequest
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.priority_store import PriorityStore
    from g2b_compare.sources.shopping_mall import CatalogPage

PRODUCT_OPERATIONS: Final = tuple(Operation)[:3]
PAGE_SIZE: Final = 10


class CatalogAdapter(Protocol):
    """Catalog capability consumed by the company crawler."""

    def fetch(
        self,
        request: ShoppingMallRequest,
        *,
        service_key: str,
    ) -> CatalogPage:
        """Fetch one typed provider page."""
        ...


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class CompanyProductCrawlResult(_FrozenModel):
    """Counts from one bounded company-product collection run."""

    calls: int
    accepted_rows: int
    quarantined_rows: int
    failures: int
    failure_reasons: tuple[str, ...]
    remaining_targets: int


class CompanyCrawlReport(_FrozenModel):
    """One company's official-row and workbook reconciliation."""

    company_name: str
    declared_product_count: int
    provider_row_count: int
    accepted_row_count: int
    quarantined_row_count: int
    unique_offer_count: int
    unique_product_count: int
    pending_operation_count: int
    provider_mismatch: int
    workbook_mismatch: int


def crawl_company_products(
    store: PriorityStore,
    adapter: CatalogAdapter,
    service_key: str,
    *,
    max_calls: int = 10_000,
) -> CompanyProductCrawlResult:
    """Collect all contract pages and retain accepted and quarantined rows."""
    calls = 0
    accepted_rows = 0
    quarantined_rows = 0
    failures = 0
    failure_reasons: list[str] = []
    observed_at = datetime.now(UTC)
    for target in store.crawl_targets(PRODUCT_OPERATIONS):
        operation = Operation(target.operation)
        page_number = target.next_page
        while calls < max_calls:
            calls += 1
            try:
                page = adapter.fetch(
                    ShoppingMallRequest(
                        operation=operation,
                        params=(
                            ("type", "json"),
                            ("pageNo", str(page_number)),
                            ("numOfRows", str(PAGE_SIZE)),
                            ("cntrctCorpNm", target.company_name),
                        ),
                        observed_at=observed_at,
                    ),
                    service_key=service_key,
                )
            except RetryableTransportError as error:
                failures += 1
                failure_reasons.append(error.reason)
                break
            accepted_rows += len(page.records)
            quarantined_rows += len(page.quarantined)
            page_size = max(1, page.page_size)
            store.save_catalog_page(
                company_name=target.company_name,
                operation=operation,
                page_number=page_number,
                page_size=page_size,
                total_count=page.total_count,
                records=page.records,
                observed_at=observed_at,
                quarantined=page.quarantined,
                request_fingerprint=page.request_fingerprint,
            )
            if page_number * page_size >= page.total_count:
                break
            page_number += 1
        if calls >= max_calls:
            break
    return CompanyProductCrawlResult(
        calls=calls,
        accepted_rows=accepted_rows,
        quarantined_rows=quarantined_rows,
        failures=failures,
        failure_reasons=tuple(failure_reasons),
        remaining_targets=len(store.crawl_targets(PRODUCT_OPERATIONS)),
    )


def read_company_crawl_report(database: Path) -> tuple[CompanyCrawlReport, ...]:
    """Reconcile provider totals, retained rows, and workbook declarations."""
    operation_values = tuple(str(operation) for operation in PRODUCT_OPERATIONS)
    query = """
        WITH page_totals AS (
            SELECT company_name, operation,
                   MAX(provider_total_count) AS provider_count,
                   SUM(accepted_count) AS accepted_count,
                   SUM(quarantined_count) AS quarantined_count
            FROM priority_company_crawl_pages
            WHERE operation IN (?, ?, ?)
            GROUP BY company_name, operation
        ), totals AS (
            SELECT company_name,
                   SUM(provider_count) AS provider_count,
                   SUM(accepted_count) AS accepted_count,
                   SUM(quarantined_count) AS quarantined_count
            FROM page_totals GROUP BY company_name
        ), offers AS (
            SELECT company_name, COUNT(*) AS offer_count,
                   COUNT(DISTINCT product_id) AS product_count
            FROM priority_product_offers
            WHERE active = 1 AND operation IN (?, ?, ?)
            GROUP BY company_name
        ), completed AS (
            SELECT company_name, COUNT(DISTINCT operation) AS operation_count
            FROM priority_crawl_state
            WHERE complete = 1 AND operation IN (?, ?, ?)
            GROUP BY company_name
        )
        SELECT company.name, company.declared_product_count,
               COALESCE(totals.provider_count, 0),
               COALESCE(totals.accepted_count, 0),
               COALESCE(totals.quarantined_count, 0),
               COALESCE(offers.offer_count, 0),
               COALESCE(offers.product_count, 0),
               3 - COALESCE(completed.operation_count, 0)
        FROM priority_companies AS company
        LEFT JOIN totals ON totals.company_name = company.name
        LEFT JOIN offers ON offers.company_name = company.name
        LEFT JOIN completed ON completed.company_name = company.name
        ORDER BY company.source_row
    """
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(query, operation_values * 3).fetchall(),
        )
    reports: list[CompanyCrawlReport] = []
    for row in rows:
        declared = _integer(row[1])
        provider = _integer(row[2])
        quarantined = _integer(row[4])
        offers = _integer(row[5])
        products = _integer(row[6])
        reports.append(
            CompanyCrawlReport(
                company_name=str(row[0]),
                declared_product_count=declared,
                provider_row_count=provider,
                accepted_row_count=_integer(row[3]),
                quarantined_row_count=quarantined,
                unique_offer_count=offers,
                unique_product_count=products,
                pending_operation_count=_integer(row[7]),
                provider_mismatch=abs(provider - offers - quarantined),
                workbook_mismatch=abs(declared - products),
            )
        )
    return tuple(reports)


def _integer(value: object) -> int:
    return value if isinstance(value, int) else int(str(value))
