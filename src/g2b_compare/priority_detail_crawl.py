"""Concurrent official detail-option collection by contract group."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from g2b_compare.priority_detail import ProductDetailAdapter
    from g2b_compare.priority_models import ProductOptionTarget
    from g2b_compare.priority_store import PriorityStore


@dataclass(frozen=True, slots=True)
class ProductDetailCrawlResult:
    """Final counts from one resumable full-detail crawl."""

    inspected_products: int
    requested_groups: int
    stored_relations: int
    failed_groups: int
    remaining_products: int


def group_targets(
    targets: Sequence[ProductOptionTarget],
) -> tuple[tuple[ProductOptionTarget, ...], ...]:
    """Group products that share one official contract dropdown response."""
    grouped: dict[str, list[ProductOptionTarget]] = {}
    for target in targets:
        grouped.setdefault(target.contract_group, []).append(target)
    return tuple(tuple(group) for group in grouped.values())


def crawl_product_details(
    store: PriorityStore,
    adapter: ProductDetailAdapter,
    *,
    max_items: int = 0,
    workers: int = 8,
) -> ProductDetailCrawlResult:
    """Collect both official child dropdowns for every pending main product."""
    groups = group_targets(store.pending_site_targets(max_items))
    inspected = 0
    relations = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(adapter.fetch, group[0]): group for group in groups
        }
        for future in as_completed(futures):
            group = futures[future]
            try:
                options = future.result()
            except RetryableTransportError:
                store.save_contract_group_result(group, (), status="retry")
                failures += 1
            else:
                store.save_contract_group_result(group, options, status="complete")
                relations += len(options)
            inspected += len(group)
    return ProductDetailCrawlResult(
        inspected_products=inspected,
        requested_groups=len(groups),
        stored_relations=relations,
        failed_groups=failures,
        remaining_products=len(store.pending_site_targets(0)),
    )
