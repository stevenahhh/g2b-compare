"""Run Todo15 HTTP, browser, cache, and process-startup distributions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

import httpx
from playwright.sync_api import sync_playwright
from pydantic import ValidationError

from g2b_compare.evaluation.benchmark import (
    BenchmarkEvidence,
    BenchmarkPlan,
    BenchmarkResult,
    benchmark_operation,
    summarize_samples,
    write_benchmark_evidence,
)
from g2b_compare.evaluation.perf_corpus import (
    PerfCorpusResult,
    generate_perf_corpus,
)
from tests.performance.benchmark_contract import CACHE_POLICY, THREADS, SearchContract
from tests.performance.benchmark_process import (
    free_port,
    terminate_process,
    wait_port_release,
    wait_ready,
)

if TYPE_CHECKING:
    from collections.abc import Generator

PRODUCT_NAME: Final = "영상감시장치-002"
QUERY: Final = {
    "category_code": "PERF-CAT-02",
    "detail_category_code": "PERF-DETAIL-002",
    "page": "1",
    "page_size": "50",
    "product_name": PRODUCT_NAME,
    "spec_text": "해상도 2MP | 15fps | 저장 13TB | 모델 PERF-00060",
}
FIRST_HTML_FAILED: Final = "first HTML contract failed"
CONTRACT_RESPONSE_FAILED: Final = "benchmark response contract failed"
CACHE_SOURCE_FAILED: Final = "cache source contract failed"


@dataclass(frozen=True, slots=True)
class HarnessError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class HarnessPaths:
    """Exact generated artifacts and final evidence destination."""

    workspace: Path
    corpus: Path
    evidence: Path


def run_harness(paths: HarnessPaths) -> tuple[BenchmarkResult, ...]:
    """Generate 50k once, exercise real surfaces, and publish one receipt."""
    result = generate_perf_corpus(paths.corpus)
    search = _http_distribution(paths, result, search_budget=True)
    cache = _http_distribution(paths, result, search_budget=False)
    html = _browser_distribution(paths, result)
    startup, first_search = _startup_distributions(paths, result)
    results = (search, cache, html, startup, first_search)
    evidence = BenchmarkEvidence(
        result.corpus_sha256,
        result.query_sha256,
        result.database_sha256,
        result.index_sha256,
        result.cache_sha256,
        THREADS,
        (
            ("search-warmups", 30),
            ("search-repetitions", 200),
            ("cache-repetitions", 200),
            ("html-repetitions", 30),
            ("startup-repetitions", 30),
            ("query-pairs", 2_000),
            ("corpus-products", 50_000),
        ),
        CACHE_POLICY,
        ("process-cold", "warm-OS-cache"),
        results,
    )
    write_benchmark_evidence(paths.evidence, evidence)
    return results


def _http_distribution(
    paths: HarnessPaths,
    result: PerfCorpusResult,
    *,
    search_budget: bool,
) -> BenchmarkResult:
    name = "search-50-with-3-slots" if search_budget else "cache-hit"
    threshold = timedelta(milliseconds=300 if search_budget else 150)
    with (
        _server(paths, result, cache_enabled=not search_budget) as base,
        httpx.Client(base_url=base, timeout=10) as client,
    ):

        def operation() -> None:
            response = client.get("/__benchmark__/contract")
            validate_contract_response(response, 0 if search_budget else 50)

        return benchmark_operation(
            BenchmarkPlan(name, 30, 200, threshold),
            operation,
        )


def _browser_distribution(
    paths: HarnessPaths,
    result: PerfCorpusResult,
) -> BenchmarkResult:
    with (
        _server(paths, result, cache_enabled=True) as base,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()

        def operation() -> None:
            context = browser.new_context()
            page = context.new_page()
            _ = page.route("**/*", lambda route: route.continue_())
            response = page.goto(base, wait_until="domcontentloaded")
            if response is None or response.status != 200:
                raise HarnessError(FIRST_HTML_FAILED)
            context.close()

        try:
            return benchmark_operation(
                BenchmarkPlan("first-html", 0, 30, timedelta(seconds=1)),
                operation,
            )
        finally:
            browser.close()


def _startup_distributions(
    paths: HarnessPaths,
    result: PerfCorpusResult,
) -> tuple[BenchmarkResult, BenchmarkResult]:
    startup: list[int] = []
    first_search: list[int] = []
    for _ in range(30):
        with tempfile.TemporaryDirectory(prefix="todo15-startup-") as raw:
            root = Path(raw)
            copied = _copy_artifacts(paths.corpus, root)
            started = time.perf_counter_ns()
            with _server(paths, result, cache_enabled=True, database=copied) as base:
                startup.append(time.perf_counter_ns() - started)
                with httpx.Client(base_url=base, timeout=10) as client:
                    search_started = time.perf_counter_ns()
                    response = client.get("/__benchmark__/contract")
                    first_search.append(time.perf_counter_ns() - search_started)
                    validate_contract_response(response, 50)
    return (
        summarize_samples(
            BenchmarkPlan("startup", 0, 30, timedelta(seconds=3)),
            tuple(startup),
        ),
        summarize_samples(
            BenchmarkPlan("first-search", 0, 30, timedelta(seconds=1.5)),
            tuple(first_search),
        ),
    )


@contextmanager
def _server(
    paths: HarnessPaths,
    result: PerfCorpusResult,
    *,
    cache_enabled: bool,
    database: Path | None = None,
) -> Generator[str]:
    port = free_port()
    env = {**os.environ, **dict(THREADS)}
    cache_path = (
        database.parent / "comparator-cache.bin"
        if database is not None
        else paths.corpus / "comparator-cache.bin"
    )
    index_path = (
        database.parent / "index.bin"
        if database is not None
        else paths.corpus / "index.bin"
    )
    env.update(
        {
            "TODO15_CACHE_ENABLED": "1" if cache_enabled else "0",
            "TODO15_CACHE": str(cache_path),
            "TODO15_CACHE_SHA": result.cache_sha256,
            "TODO15_DATABASE": str(database or paths.corpus / "perf.sqlite3"),
            "TODO15_DATABASE_SHA": result.database_sha256,
            "TODO15_INDEX": str(index_path),
            "TODO15_INDEX_SHA": result.index_sha256,
            "TODO15_PRODUCT_NAME": PRODUCT_NAME,
            "TODO15_SPEC_TEXT": QUERY["spec_text"],
            "TODO15_CATEGORY_CODE": QUERY["category_code"],
            "TODO15_DETAIL_CATEGORY_CODE": QUERY["detail_category_code"],
        }
    )
    log_path = paths.evidence.parent / f"uvicorn-{port}.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(  # noqa: S603 -- fixed interpreter and module argv
            server_command(sys.executable, port),
            cwd=paths.workspace,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            wait_ready(base, process)
            yield base
        finally:
            terminate_process(process)
            wait_port_release(port)


def server_command(python_executable: str, port: int) -> tuple[str, ...]:
    """Return the fixed one-worker Uvicorn benchmark command."""
    return (
        python_executable,
        "-m",
        "uvicorn",
        "tests.performance.serve_perf_app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
        "--log-level",
        "warning",
    )


def validate_contract_response(
    response: httpx.Response,
    expected_cache_hits: int,
) -> None:
    if response.status_code != 200:
        raise HarnessError(CONTRACT_RESPONSE_FAILED)
    try:
        contract = SearchContract.model_validate_json(response.content)
    except ValidationError as error:
        raise HarnessError(CONTRACT_RESPONSE_FAILED) from error
    if contract.cache_hits != expected_cache_hits:
        raise HarnessError(CACHE_SOURCE_FAILED)


def _copy_artifacts(source: Path, target: Path) -> Path:
    for name in ("perf.sqlite3", "index.bin", "comparator-cache.bin"):
        _ = shutil.copy2(source / name, target / name)
    return target / "perf.sqlite3"
