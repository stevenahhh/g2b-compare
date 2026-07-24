from __future__ import annotations

import pytest
from httpx import Response
from pydantic import ValidationError

from tests.performance.benchmark_contract import (
    ComparatorContract,
    ResultContract,
    SearchContract,
)
from tests.performance.benchmark_harness import HarnessError, validate_contract_response


def _result(index: int) -> ResultContract:
    product_id = f"PERF-002-{index:03d}"

    def comparator(rank: int) -> ComparatorContract:
        return ComparatorContract(
            anchor_id=product_id,
            rank=rank,
            status="ok",
            candidate_id=f"PERF-002-{(index + rank) % 60:03d}",
        )

    return ResultContract(
        product_id=product_id,
        comparators=(comparator(1), comparator(2), comparator(3)),
    )


def test_contract_accepts_exact_50_rows_and_three_cache_slots() -> None:
    contract = SearchContract(
        status="ok",
        total_results=60,
        page_size=50,
        cache_hits=50,
        results=tuple(_result(index) for index in range(50)),
    )

    assert len(contract.results) == 50
    assert all(len(result.comparators) == 3 for result in contract.results)
    assert contract.cache_hits == 50


def test_contract_rejects_49_rows() -> None:
    with pytest.raises(ValidationError, match="result-count"):
        _ = SearchContract(
            status="ok",
            total_results=60,
            page_size=50,
            cache_hits=0,
            results=tuple(_result(index) for index in range(49)),
        )


def test_contract_rejects_non_cache_hit_claim() -> None:
    with pytest.raises(ValidationError, match="cache-hit-count"):
        _ = SearchContract(
            status="ok",
            total_results=60,
            page_size=50,
            cache_hits=49,
            results=tuple(_result(index) for index in range(50)),
        )


def test_contract_rejects_slot_anchor_or_rank_drift() -> None:
    first = _result(0)
    invalid = ResultContract.model_construct(
        product_id=first.product_id,
        comparators=(
            ComparatorContract(
                anchor_id="PERF-002-999",
                rank=2,
                status="ok",
                candidate_id="PERF-002-001",
            ),
            *first.comparators[1:],
        ),
    )

    with pytest.raises(ValidationError, match="comparator-contract"):
        _ = SearchContract(
            status="ok",
            total_results=60,
            page_size=50,
            cache_hits=0,
            results=(invalid, *tuple(_result(index) for index in range(1, 50))),
        )


def test_live_validator_distinguishes_search_from_cache_hit() -> None:
    search = SearchContract(
        status="ok",
        total_results=60,
        page_size=50,
        cache_hits=0,
        results=tuple(_result(index) for index in range(50)),
    )
    cache = search.model_copy(update={"cache_hits": 50})

    validate_contract_response(Response(200, content=search.model_dump_json()), 0)
    validate_contract_response(Response(200, content=cache.model_dump_json()), 50)


def test_live_validator_rejects_cache_lane_without_hits() -> None:
    search = SearchContract(
        status="ok",
        total_results=60,
        page_size=50,
        cache_hits=0,
        results=tuple(_result(index) for index in range(50)),
    )

    with pytest.raises(HarnessError, match="cache source contract failed"):
        validate_contract_response(Response(200, content=search.model_dump_json()), 50)
