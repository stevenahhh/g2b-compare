"""Todo15 exact aggregate failure scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from g2b_compare.evaluation.benchmark import (
    BenchmarkPlan,
    BenchmarkThresholdError,
    benchmark_operation,
)
from g2b_compare.evaluation.contracts import (
    ExternalContractFacts,
    ParserContractFacts,
    PerfContractFacts,
    RankingContractFacts,
    Todo15ContractError,
    validate_external_contract,
    validate_parser_contract,
    validate_perf_contract,
    validate_ranking_contract,
)
from tests.acceptance.todo_15_integrity_scenarios import (
    run_integrity_failure,
    validate_integrity_happy,
)
from tests.acceptance.todo_15_runner_scenarios import (
    run_strict_runner_failure,
    validate_strict_runner_happy,
)

if TYPE_CHECKING:
    from pathlib import Path

type Scenario = Literal[
    "slow-search",
    "slow-cache",
    "slow-html",
    "slow-startup",
    "cache-disabled",
    "perf-field-drift",
    "perf-overlap-rule",
    "query-selection-drift",
    "thread-env-missing",
    "corpus-hash-mismatch",
    "category-leak",
    "secret-runtime",
    "source-mutation",
    "insufficient-gold",
    "wrong-anchor-count",
    "wrong-candidate-count",
    "missing-gold-manifest",
    "gold-hash-mismatch",
    "single-assessor",
    "assessor-not-independent",
    "blinded-order-drift",
    "incomplete-double-label",
    "missing-adjudication",
    "invalid-adjudication",
    "split-count",
    "split-leakage",
    "parser-gold-count",
    "parser-negative-row",
    "parser-compound-span-count",
    "parser-byte-boundary",
    "parser-semantic-mismatch",
    "parser-duplicate-prediction",
    "parser-precision",
    "parser-recall",
    "metric-relevance-threshold",
    "metric-dcg-formula",
    "metric-macro-aggregation",
    "lexical-baseline-drift",
    "non-heldout-threshold",
    "ranking-regression",
    "misleading-success-output",
    "parser-dimension-semantic-count",
    "parser-shared-span-semantics",
    "parser-semantic-total",
    "evaluation-unjudged-candidate",
    "judged-pool-full-v1",
    "judged-pool-lexical",
]
type PerfFailure = Literal[
    "cache-disabled",
    "perf-field-drift",
    "perf-overlap-rule",
    "query-selection-drift",
    "thread-env-missing",
    "corpus-hash-mismatch",
]


@dataclass(frozen=True, slots=True)
class FailureObservation:
    """Stable exception identity and message for registry binding."""

    assertion_class: str
    message: str


def validate_happy(temp_root: Path) -> None:
    """Exercise every fast aggregate contract with exact valid facts."""
    validate_perf_contract(PerfContractFacts())
    validate_external_contract(ExternalContractFacts())
    validate_parser_contract(ParserContractFacts())
    validate_ranking_contract(RankingContractFacts())
    validate_integrity_happy()
    validate_strict_runner_happy(temp_root)


def observe_failure(scenario: Scenario, temp_root: Path) -> FailureObservation:
    """Execute exactly one mutation and capture its typed failure."""
    try:
        _run_failure(scenario, temp_root)
    except (Todo15ContractError, BenchmarkThresholdError) as error:
        return FailureObservation(type(error).__name__, str(error))
    detail = f"scenario did not fail: {scenario}"
    raise AssertionError(detail)


def _run_failure(scenario: Scenario, temp_root: Path) -> None:
    match scenario:  # noqa: MATCH_OK -- Scenario union is already exhaustive
        case "slow-search" | "slow-cache" | "slow-html" | "slow-startup":
            _slow(scenario)
        case (
            "cache-disabled"
            | "perf-field-drift"
            | "perf-overlap-rule"
            | "query-selection-drift"
            | "thread-env-missing"
            | "corpus-hash-mismatch"
        ):
            _perf(scenario)
        case "secret-runtime" | "source-mutation":
            run_integrity_failure(scenario, temp_root)
        case (
            "insufficient-gold"
            | "wrong-anchor-count"
            | "wrong-candidate-count"
            | "missing-gold-manifest"
            | "gold-hash-mismatch"
            | "single-assessor"
            | "assessor-not-independent"
            | "blinded-order-drift"
            | "incomplete-double-label"
            | "missing-adjudication"
            | "invalid-adjudication"
            | "split-count"
            | "split-leakage"
        ):
            _external(scenario)
        case "parser-recall" | "ranking-regression" | "evaluation-unjudged-candidate":
            run_strict_runner_failure(scenario, temp_root)
        case (
            "parser-gold-count"
            | "parser-negative-row"
            | "parser-compound-span-count"
            | "parser-byte-boundary"
            | "parser-semantic-mismatch"
            | "parser-duplicate-prediction"
            | "parser-precision"
            | "parser-dimension-semantic-count"
            | "parser-shared-span-semantics"
            | "parser-semantic-total"
        ):
            _parser(scenario)
        case (
            "category-leak"
            | "metric-relevance-threshold"
            | "metric-dcg-formula"
            | "metric-macro-aggregation"
            | "lexical-baseline-drift"
            | "non-heldout-threshold"
            | "misleading-success-output"
            | "judged-pool-full-v1"
            | "judged-pool-lexical"
        ):
            _ranking(scenario)


def _slow(scenario: str) -> None:
    ticks = iter((0, 2_000_000))

    def clock() -> int:
        return next(ticks)

    _ = benchmark_operation(
        BenchmarkPlan(scenario, 0, 1, timedelta(milliseconds=1)),
        lambda: None,
        clock_ns=clock,
    )


def _perf(scenario: PerfFailure) -> None:
    facts = PerfContractFacts()
    match scenario:  # noqa: MATCH_OK -- PerfFailure union is already exhaustive
        case "cache-disabled":
            facts = replace(facts, cache_enabled=False)
        case "perf-field-drift":
            facts = replace(facts, products=49_999)
        case "perf-overlap-rule":
            facts = replace(facts, overlap_rule_valid=False)
        case "query-selection-drift":
            facts = replace(facts, queries=199)
        case "thread-env-missing":
            facts = replace(facts, thread_environment=())
        case "corpus-hash-mismatch":
            facts = replace(facts, hashes=("bad",) * 5)
    validate_perf_contract(facts)


def _external(scenario: str) -> None:
    facts = ExternalContractFacts()
    changes = {
        "insufficient-gold": replace(facts, anchors=0),
        "wrong-anchor-count": replace(facts, anchors=199),
        "wrong-candidate-count": replace(facts, candidates_per_anchor=9),
        "missing-gold-manifest": replace(facts, manifest_present=False),
        "gold-hash-mismatch": replace(facts, hashes_match=False),
        "single-assessor": replace(facts, assessor_ids=("alpha", "alpha")),
        "assessor-not-independent": replace(facts, adjudicator_id="beta"),
        "blinded-order-drift": replace(facts, blinded_order_valid=False),
        "incomplete-double-label": replace(facts, complete_double_labels=False),
        "missing-adjudication": replace(facts, adjudication_complete=False),
        "invalid-adjudication": replace(facts, adjudication_valid=False),
        "split-count": replace(facts, split_counts=(121, 39, 40)),
        "split-leakage": replace(facts, split_leakage=1),
    }
    validate_external_contract(changes[scenario])


def _parser(scenario: str) -> None:
    facts = ParserContractFacts()
    changes = {
        "parser-gold-count": replace(facts, rows=499),
        "parser-negative-row": replace(facts, negative_rows=49),
        "parser-compound-span-count": replace(facts, compound_span_count_valid=False),
        "parser-byte-boundary": replace(facts, byte_boundaries_valid=False),
        "parser-semantic-mismatch": replace(facts, semantics_match=False),
        "parser-duplicate-prediction": replace(facts, duplicate_predictions=1),
        "parser-precision": replace(facts, precision=Decimal("0.979999")),
        "parser-recall": replace(facts, recall=Decimal("0.899999")),
        "parser-dimension-semantic-count": replace(
            facts, dimension_semantic_count_valid=False
        ),
        "parser-shared-span-semantics": replace(
            facts, shared_span_semantics_valid=False
        ),
        "parser-semantic-total": replace(facts, semantic_results=599),
    }
    validate_parser_contract(changes[scenario])


def _ranking(scenario: str) -> None:
    facts = RankingContractFacts()
    changes = {
        "category-leak": replace(facts, category_leakage=1),
        "metric-relevance-threshold": replace(facts, relevance_threshold=1),
        "metric-dcg-formula": replace(facts, dcg_formula="linear"),
        "metric-macro-aggregation": replace(facts, aggregation="pair-micro"),
        "lexical-baseline-drift": replace(facts, lexical_ndcg=Decimal("0.71")),
        "non-heldout-threshold": replace(facts, held_out_only=False),
        "ranking-regression": replace(facts, full_precision=Decimal("0.79")),
        "misleading-success-output": replace(facts, success_output_truthful=False),
        "evaluation-unjudged-candidate": replace(facts, unjudged_candidates=1),
        "judged-pool-full-v1": replace(facts, full_v1_exact_three=False),
        "judged-pool-lexical": replace(facts, lexical_exact_three=False),
    }
    validate_ranking_contract(changes[scenario])
