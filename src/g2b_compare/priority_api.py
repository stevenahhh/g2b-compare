"""Resumable official-API collection for priority companies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.shopping_mall import ShoppingMallRequest
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from g2b_compare.priority_store import PriorityStore
    from g2b_compare.sources.shopping_mall import ShoppingMallAdapter

OPERATIONS: Final = tuple(Operation)[:3]
PAGE_SIZE: Final = 1000


@dataclass(frozen=True, slots=True)
class ApiCrawlResult:
    """Counts from one bounded, resumable API run."""

    calls: int
    products: int
    failures: int
    remaining_targets: int


def crawl_priority_companies(
    store: PriorityStore,
    adapter: ShoppingMallAdapter,
    service_key: str,
    *,
    max_calls: int = 10_000,
) -> ApiCrawlResult:
    """Collect every page for each priority company up to the local ceiling."""
    calls = 0
    stored = 0
    failures = 0
    observed_at = datetime.now(UTC)
    for target in store.crawl_targets(OPERATIONS):
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
            except RetryableTransportError:
                failures += 1
                break
            stored += len(page.records)
            store.save_catalog_page(
                company_name=target.company_name,
                operation=operation,
                page_number=page_number,
                page_size=max(1, page.page_size),
                total_count=page.total_count,
                records=page.records,
                observed_at=observed_at,
            )
            if page_number * max(1, page.page_size) >= page.total_count:
                break
            page_number += 1
        if calls >= max_calls:
            break
    return ApiCrawlResult(
        calls=calls,
        products=stored,
        failures=failures,
        remaining_targets=len(store.crawl_targets(OPERATIONS)),
    )
