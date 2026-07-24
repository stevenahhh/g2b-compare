# ruff: noqa: INP001
"""Collect official main-product child relations for the local catalog."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

from g2b_compare.priority_detail import HttpProductDetailAdapter
from g2b_compare.priority_detail_crawl import crawl_product_details
from g2b_compare.priority_store import PriorityStore


class _Options(argparse.Namespace):
    home: Path = Path(".g2b")
    workers: int = 8
    max_items: int = 0


def main(arguments: list[str] | None = None) -> int:
    """Run the resumable public detail-option batch."""
    options = _Options()
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--home", type=Path, default=Path(".g2b"))
    _ = parser.add_argument("--workers", type=int, default=8)
    _ = parser.add_argument("--max-items", type=int, default=0)
    _ = parser.parse_args(arguments, namespace=options)
    worker_count = max(1, options.workers)
    limits = httpx.Limits(
        max_connections=worker_count,
        max_keepalive_connections=worker_count,
        keepalive_expiry=30,
    )
    timeout = httpx.Timeout(connect=5, read=30, write=10, pool=10)
    store = PriorityStore(options.home / "g2b.sqlite3")
    with httpx.Client(
        trust_env=False,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        result = crawl_product_details(
            store,
            HttpProductDetailAdapter(client),
            max_items=max(0, options.max_items),
            workers=worker_count,
        )
    _ = sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    return int(result.failed_groups > 0 or result.remaining_products > 0)


if __name__ == "__main__":
    raise SystemExit(main())
