"""Command-line entry point for priority workbook and crawler operations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Final

import httpx

from g2b_compare.contracts.wire import HttpxRequester
from g2b_compare.priority_api import crawl_priority_companies
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
    _write(store.status().model_dump_json())
    return 0


def _write(value: str) -> None:
    _ = sys.stdout.write(value + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
