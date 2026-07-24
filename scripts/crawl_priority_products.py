# ruff: noqa: INP001
"""Collect and reconcile every priority company's main products."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Final

import httpx

from g2b_compare.company_product_crawl import (
    crawl_company_products,
    read_company_crawl_report,
)
from g2b_compare.contracts.wire import HttpxRequester
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_DIR: Final = PROJECT_ROOT / ".omo/evidence/ulw-main-products"
PRIORITY_COMPANY_COUNT: Final = 55


class _Options(argparse.Namespace):
    home: Path = Path(".g2b")
    max_calls: int = 10_000
    verify_counts: bool = False


def main(arguments: list[str] | None = None) -> int:
    """Run the copied company-main-product crawler and write its audit."""
    options = _Options()
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--home", type=Path, default=Path(".g2b"))
    _ = parser.add_argument("--max-calls", type=int, default=10_000)
    _ = parser.add_argument("--verify-counts", action="store_true")
    _ = parser.parse_args(arguments, namespace=options)

    service_key = _service_key()
    if not service_key:
        _ = sys.stderr.write("G2B_SERVICE_KEY가 필요함\n")
        return 2

    store = PriorityStore(options.home / "g2b.sqlite3")
    with httpx.Client(trust_env=False) as client:
        result = crawl_company_products(
            store,
            ShoppingMallAdapter(
                HttpTransport(HttpxRequester(client), max_attempts=1)
            ),
            service_key,
            max_calls=max(1, options.max_calls),
        )
    companies = read_company_crawl_report(store.database)
    mismatches = tuple(
        company
        for company in companies
        if company.pending_operation_count
        or company.provider_mismatch
        or company.workbook_mismatch
    )
    passed = (
        len(companies) == PRIORITY_COMPANY_COUNT
        and result.failures == 0
        and result.remaining_targets == 0
        and not mismatches
    )
    payload = {
        "status": "pass" if passed else "incomplete",
        "company_count": len(companies),
        "calls": result.calls,
        "accepted_rows": result.accepted_rows,
        "quarantined_rows": result.quarantined_rows,
        "failures": result.failures,
        "failure_reasons": list(result.failure_reasons),
        "remaining_targets": result.remaining_targets,
        "mismatch_company_count": len(mismatches),
        "companies": [company.model_dump(mode="json") for company in companies],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _ = (EVIDENCE_DIR / "crawl-summary.json").write_text(
        rendered + "\n", "utf-8"
    )
    _ = (EVIDENCE_DIR / "crawl-run.log").write_text(rendered + "\n", "utf-8")
    _ = sys.stdout.write(rendered + "\n")
    return int(options.verify_counts and not passed)


def _service_key() -> str:
    current = os.environ.get("G2B_SERVICE_KEY", "").strip()
    if current:
        return current
    dotenv = PROJECT_ROOT / ".env"
    if not dotenv.is_file():
        return ""
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if line.startswith("G2B_SERVICE_KEY="):
            return line.removeprefix("G2B_SERVICE_KEY=").strip().strip("\"'")
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
