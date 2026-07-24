"""Uvicorn import target backed by the exact perf-v1 production adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from g2b_compare.evaluation.perf_reader import (
    PerfReaderArtifacts,
    PerfSearchReader,
    perf_release_pin,
)
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchRequest
from g2b_compare.web.app import create_app
from tests.performance.benchmark_contract import (
    ObservedReader,
    SearchContract,
    contract_from_response,
)

DATABASE: Final = Path(os.environ["TODO15_DATABASE"])
PRODUCT_NAME: Final = os.environ["TODO15_PRODUCT_NAME"]
SPEC_TEXT: Final = os.environ["TODO15_SPEC_TEXT"]
CATEGORY_CODE: Final = os.environ["TODO15_CATEGORY_CODE"]
DETAIL_CATEGORY_CODE: Final = os.environ["TODO15_DETAIL_CATEGORY_CODE"]
PIN: Final = perf_release_pin(
    database_sha256=os.environ["TODO15_DATABASE_SHA"],
    index_sha256=os.environ["TODO15_INDEX_SHA"],
    cache_sha256=os.environ["TODO15_CACHE_SHA"],
)
PERF_READER: Final = PerfSearchReader(
    PerfReaderArtifacts(
        DATABASE,
        Path(os.environ["TODO15_CACHE"]),
        Path(os.environ["TODO15_INDEX"]),
    ),
    PIN,
    cache_enabled=os.environ.get("TODO15_CACHE_ENABLED") == "1",
)
if os.environ.get("TODO15_CACHE_ENABLED") == "1":
    _ = PERF_READER.warm_cache(PRODUCT_NAME)

READER: Final = ObservedReader(PERF_READER)
app = create_app(reader=READER)


@app.get("/__benchmark__/contract", response_model=SearchContract)
def benchmark_contract() -> SearchContract:
    before = READER.cache_hits
    response = execute_search(
        SearchRequest(
            product_name=PRODUCT_NAME,
            category_code=CATEGORY_CODE,
            detail_category_code=DETAIL_CATEGORY_CODE,
            spec_text=SPEC_TEXT,
            page=1,
            page_size=50,
        ),
        READER,
    )
    return contract_from_response(response, READER.cache_hits - before)
