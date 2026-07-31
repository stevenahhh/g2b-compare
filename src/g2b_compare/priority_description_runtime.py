"""Live runtime composition for resumable product-description enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.db.raw import RawBlobStore

from .priority_description_client import G2bProductDescriptionClient
from .priority_description_crawl import (
    DescriptionCrawlOptions,
    DescriptionCrawlSummary,
    crawl_product_descriptions,
)
from .priority_description_store import ProductDescriptionStore

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class LiveDescriptionRun:
    """Reconciled result of one explicit live description crawl."""

    summary: DescriptionCrawlSummary
    latest_outcomes: dict[str, int]
    pending_targets: int


@dataclass(frozen=True, slots=True)
class LiveDescriptionOptions:
    """Selection and concurrency policy for one explicit live run."""

    concurrency: int
    limit: int | None
    retry_missing: bool
    force: bool


async def run_live_product_description_crawl(
    database: Path,
    raw_root: Path,
    options: LiveDescriptionOptions,
) -> LiveDescriptionRun:
    """Bootstrap one public session and enrich every selected main product."""
    store = ProductDescriptionStore(database)
    targets = store.pending_targets(
        retry_missing=options.retry_missing,
        force=options.force,
        limit=options.limit,
    )
    if not targets:
        return LiveDescriptionRun(
            summary=DescriptionCrawlSummary(0, 0, 0, 0, 0, None),
            latest_outcomes=store.outcome_counts(),
            pending_targets=0,
        )
    async with G2bProductDescriptionClient(targets[0]) as client:
        summary = await crawl_product_descriptions(
            store,
            RawBlobStore(raw_root),
            client,
            targets,
            DescriptionCrawlOptions(concurrency=options.concurrency),
        )
    return LiveDescriptionRun(
        summary=summary,
        latest_outcomes=store.outcome_counts(),
        pending_targets=len(store.pending_targets()),
    )
