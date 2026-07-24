# ruff: noqa: INP001
"""Collect all priority-company products from the public Shopping Mall site."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

import httpx

from g2b_compare.company_site_crawl import (
    crawl_company_site_products,
    read_company_site_crawl_report,
)
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_site import HttpShoppingSiteAdapter

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_DIR: Final = PROJECT_ROOT / ".omo/evidence/ulw-main-products"
PRIORITY_COMPANY_COUNT: Final = 55


class _Options(argparse.Namespace):
    home: Path = Path(".g2b")
    workers: int = 8


def main(arguments: list[str] | None = None) -> int:
    """Run the keyless site crawler and write exact count evidence."""
    options = _Options()
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--home", type=Path, default=Path(".g2b"))
    _ = parser.add_argument("--workers", type=int, default=8)
    _ = parser.parse_args(arguments, namespace=options)

    store = PriorityStore(options.home / "g2b.sqlite3")
    limits = httpx.Limits(
        max_connections=max(1, options.workers),
        max_keepalive_connections=max(1, options.workers),
    )
    with httpx.Client(
        trust_env=False,
        timeout=httpx.Timeout(30),
        limits=limits,
    ) as client:
        result = crawl_company_site_products(
            store,
            HttpShoppingSiteAdapter(client),
            workers=max(1, options.workers),
        )
    companies = read_company_site_crawl_report(store.database)
    mismatches = tuple(
        company
        for company in companies
        if company.pending or company.provider_mismatch
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
    _ = (EVIDENCE_DIR / "site-crawl-summary.json").write_text(
        rendered + "\n", "utf-8"
    )
    _ = sys.stdout.write(rendered + "\n")
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
