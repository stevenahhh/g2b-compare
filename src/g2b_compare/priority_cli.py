"""Command-line entry point for priority workbook and crawler operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Final

import httpx

from g2b_compare.contracts.wire import HttpxRequester
from g2b_compare.priority_api import crawl_priority_companies
from g2b_compare.priority_description_client import ProductDescriptionBootstrapError
from g2b_compare.priority_description_runtime import (
    LiveDescriptionOptions,
    run_live_product_description_crawl,
)
from g2b_compare.priority_site import crawl_product_options
from g2b_compare.priority_store import PriorityStore
from g2b_compare.priority_workbook import read_priority_workbook
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport, RetryableTransportError

DEFAULT_DATABASE: Final = Path(".g2b/mvp.sqlite3")
DEFAULT_WORKBOOK: Final = Path(
    "dataset/우수조달물품 업체소재별현황 및 우수옵션(260629).xlsm"
)


class _Options(argparse.Namespace):
    database: Path = DEFAULT_DATABASE
    command: str = ""
    workbook: Path = DEFAULT_WORKBOOK
    max_calls: int = 10_000
    max_items: int = 0
    headed: bool = False
    concurrency: int = 8
    detail_limit: int | None = None
    retry_missing: bool = False
    force: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="g2b-priority")
    _ = parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    _ = importer.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    api = commands.add_parser("api")
    _ = api.add_argument("--max-calls", type=int, default=10_000)
    site = commands.add_parser("site")
    _ = site.add_argument("--max-items", type=int, default=0)
    _ = site.add_argument("--headed", action="store_true")
    details = commands.add_parser("crawl-details")
    _ = details.add_argument("--concurrency", type=int, default=8)
    _ = details.add_argument("--detail-limit", type=int, default=None)
    _ = details.add_argument("--retry-missing", action="store_true")
    _ = details.add_argument("--force", action="store_true")
    _ = commands.add_parser("status")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run one explicit collection action and print compact JSON."""
    options = _Options()
    _ = _parser().parse_args(arguments, namespace=options)
    database = options.database
    store = PriorityStore(database)
    if options.command == "import":
        store.replace_dataset(read_priority_workbook(options.workbook))
        _write(store.status().model_dump_json())
        return 0
    if options.command == "api":
        return _run_api(options, store)
    if options.command == "site":
        result = crawl_product_options(
            store,
            max_items=max(0, options.max_items),
            headless=not options.headed,
        )
        _write(
            json.dumps(
                {
                    "inspected": result.inspected,
                    "relations": result.relations,
                    "failed": result.failed,
                },
                separators=(",", ":"),
            )
        )
        return 0
    if options.command == "crawl-details":
        return _run_crawl_details(options, database)
    _write(store.status().model_dump_json())
    return 0


def _run_api(options: _Options, store: PriorityStore) -> int:
    service_key = os.environ.get("G2B_SERVICE_KEY", "").strip()
    if not service_key:
        _ = sys.stderr.write("G2B_SERVICE_KEY가 필요함\n")
        return 2
    try:
        with httpx.Client(trust_env=False) as client:
            result = crawl_priority_companies(
                store,
                ShoppingMallAdapter(
                    HttpTransport(HttpxRequester(client), max_attempts=1)
                ),
                service_key,
                max_calls=max(1, options.max_calls),
            )
    except RetryableTransportError as error:
        _write(
            json.dumps(
                {
                    "status": "paused",
                    "reason": error.reason,
                    "remaining_targets": store.status().pending_api_target_count,
                },
                separators=(",", ":"),
            )
        )
        return 0
    _write(
        json.dumps(
            {
                "calls": result.calls,
                "products": result.products,
                "failures": result.failures,
                "remaining_targets": result.remaining_targets,
            },
            separators=(",", ":"),
        )
    )
    return 0


def _run_crawl_details(options: _Options, database: Path) -> int:
    try:
        result = asyncio.run(
            run_live_product_description_crawl(
                database,
                database.parent / "raw",
                LiveDescriptionOptions(
                    concurrency=options.concurrency,
                    limit=options.detail_limit,
                    retry_missing=options.retry_missing,
                    force=options.force,
                ),
            )
        )
    except ProductDescriptionBootstrapError:
        _write(
            json.dumps(
                {
                    "status": "aborted",
                    "abort_code": "bootstrap_failed",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    summary = result.summary
    complete = (
        summary.abort_code is None
        and summary.failed == 0
        and result.pending_targets == 0
    )
    _write(
        json.dumps(
            {
                "status": "complete" if complete else "paused",
                "attempted": summary.attempted,
                "stored": summary.stored,
                "missing": summary.missing,
                "failed": summary.failed,
                "remaining": summary.remaining,
                "abort_code": summary.abort_code,
                "latest_outcomes": result.latest_outcomes,
                "pending_targets": result.pending_targets,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if complete else 1


def _write(value: str) -> None:
    _ = sys.stdout.write(value + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
