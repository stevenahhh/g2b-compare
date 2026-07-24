"""Fast aggregate contracts checked before expensive Todo15 evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, override

SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_COUNT: Final = 5
ANCHOR_COUNT: Final = 200
CANDIDATE_COUNT: Final = 10
ASSESSOR_COUNT: Final = 2
INDEPENDENT_IDENTITY_COUNT: Final = 3
PARSER_ROW_COUNT: Final = 500
PARSER_NEGATIVE_COUNT: Final = 50
PARSER_SPAN_COUNT: Final = 500
PARSER_SEMANTIC_COUNT: Final = 600
RELEVANCE_THRESHOLD: Final = 2
REQUIRED_THREADS: Final = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
}


@dataclass(frozen=True, slots=True)
class Todo15ContractError(Exception):
    """Name the first aggregate release contract that failed."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class PerfContractFacts:
    """Deterministic corpus, query, environment, and artifact facts."""

    products: int = 50_000
    queries: int = 200
    structured: int = 35_000
    missing_price: int = 5_000
    mixed_unit: int = 2_500
    price_queries: int = 140
    spec_queries: int = 180
    hashes: tuple[str, ...] = ("a" * 64,) * 5
    thread_environment: tuple[tuple[str, str], ...] = tuple(REQUIRED_THREADS.items())
    cache_enabled: bool = True
    overlap_rule_valid: bool = True


@dataclass(frozen=True, slots=True)
class ExternalContractFacts:
    """Externally supplied label population and independence facts."""

    manifest_present: bool = True
    hashes_match: bool = True
    anchors: int = 200
    candidates_per_anchor: int = 10
    assessor_ids: tuple[str, str] = ("alpha", "beta")
    adjudicator_id: str = "gamma"
    blinded_order_valid: bool = True
    complete_double_labels: bool = True
    adjudication_complete: bool = True
    adjudication_valid: bool = True
    split_counts: tuple[int, int, int] = (120, 40, 40)
    split_leakage: int = 0


@dataclass(frozen=True, slots=True)
class ParserContractFacts:
    """Parser-gold structure, aggregate, and measured held-out facts."""

    rows: int = 500
    negative_rows: int = 50
    positive_spans: int = 500
    semantic_results: int = 600
    compound_span_count_valid: bool = True
    dimension_semantic_count_valid: bool = True
    shared_span_semantics_valid: bool = True
    byte_boundaries_valid: bool = True
    semantics_match: bool = True
    duplicate_predictions: int = 0
    precision: Decimal = Decimal("0.98")
    recall: Decimal = Decimal("0.90")


@dataclass(frozen=True, slots=True)
class RankingContractFacts:
    """Judged-pool and held-out ranking calculation facts."""

    category_leakage: int = 0
    relevance_threshold: int = 2
    dcg_formula: str = "graded-log2"
    aggregation: str = "anchor-macro"
    held_out_only: bool = True
    pool_deterministic: bool = True
    full_v1_exact_three: bool = True
    lexical_exact_three: bool = True
    unjudged_candidates: int = 0
    full_precision: Decimal = Decimal("0.80")
    full_ndcg: Decimal = Decimal("0.73")
    lexical_precision: Decimal = Decimal("0.79")
    lexical_ndcg: Decimal = Decimal("0.70")
    success_output_truthful: bool = True


@dataclass(frozen=True, slots=True)
class IntegrityContractFacts:
    """Runtime secret scan and immutable source receipt facts."""

    runtime_secret_matches: int = 0
    source_hashes_match: bool = True


def validate_perf_contract(facts: PerfContractFacts) -> None:
    """Validate exact perf-v1 counts, receipts, and locked thread variables."""
    checks = (
        (facts.cache_enabled, "cache-disabled"),
        (
            (facts.products, facts.structured, facts.missing_price, facts.mixed_unit)
            == (50_000, 35_000, 5_000, 2_500),
            "perf-field-drift",
        ),
        (facts.overlap_rule_valid, "perf-overlap-rule"),
        (
            (facts.queries, facts.price_queries, facts.spec_queries) == (200, 140, 180),
            "query-selection-drift",
        ),
        (
            dict(facts.thread_environment) == REQUIRED_THREADS,
            "thread-env-missing",
        ),
        (
            len(facts.hashes) == ARTIFACT_COUNT
            and all(SHA256.fullmatch(value) is not None for value in facts.hashes),
            "corpus-hash-mismatch",
        ),
    )
    _require(checks)


def validate_external_contract(facts: ExternalContractFacts) -> None:
    """Validate external completeness without claiming assessor independence."""
    identities = {*facts.assessor_ids, facts.adjudicator_id}
    checks = (
        (facts.manifest_present, "missing-gold-manifest"),
        (facts.hashes_match, "gold-hash-mismatch"),
        (facts.anchors >= 1, "insufficient-gold"),
        (facts.anchors == ANCHOR_COUNT, "wrong-anchor-count"),
        (
            facts.candidates_per_anchor == CANDIDATE_COUNT,
            "wrong-candidate-count",
        ),
        (len(set(facts.assessor_ids)) == ASSESSOR_COUNT, "single-assessor"),
        (
            len(identities) == INDEPENDENT_IDENTITY_COUNT,
            "assessor-not-independent",
        ),
        (facts.blinded_order_valid, "blinded-order-drift"),
        (facts.complete_double_labels, "incomplete-double-label"),
        (facts.adjudication_complete, "missing-adjudication"),
        (facts.adjudication_valid, "invalid-adjudication"),
        (facts.split_counts == (120, 40, 40), "split-count"),
        (facts.split_leakage == 0, "split-leakage"),
    )
    _require(checks)


def validate_parser_contract(facts: ParserContractFacts) -> None:
    """Validate parser-gold shape and exact held-out unit metrics."""
    checks = (
        (facts.rows == PARSER_ROW_COUNT, "parser-gold-count"),
        (facts.negative_rows == PARSER_NEGATIVE_COUNT, "parser-negative-row"),
        (facts.compound_span_count_valid, "parser-compound-span-count"),
        (facts.dimension_semantic_count_valid, "parser-dimension-semantic-count"),
        (facts.shared_span_semantics_valid, "parser-shared-span-semantics"),
        (facts.positive_spans == PARSER_SPAN_COUNT, "parser-semantic-total"),
        (
            facts.semantic_results == PARSER_SEMANTIC_COUNT,
            "parser-semantic-total",
        ),
        (facts.byte_boundaries_valid, "parser-byte-boundary"),
        (facts.semantics_match, "parser-semantic-mismatch"),
        (facts.duplicate_predictions == 0, "parser-duplicate-prediction"),
        (facts.precision >= Decimal("0.98"), "parser-precision"),
        (facts.recall >= Decimal("0.90"), "parser-recall"),
    )
    _require(checks)


def validate_ranking_contract(facts: RankingContractFacts) -> None:
    """Validate exact judged pools, calculation policy, and ranking thresholds."""
    checks = (
        (facts.category_leakage == 0, "category-leak"),
        (
            facts.relevance_threshold == RELEVANCE_THRESHOLD,
            "metric-relevance-threshold",
        ),
        (facts.dcg_formula == "graded-log2", "metric-dcg-formula"),
        (facts.aggregation == "anchor-macro", "metric-macro-aggregation"),
        (facts.held_out_only, "non-heldout-threshold"),
        (facts.pool_deterministic, "judged-pool-full-v1"),
        (facts.full_v1_exact_three, "judged-pool-full-v1"),
        (facts.lexical_exact_three, "judged-pool-lexical"),
        (facts.unjudged_candidates == 0, "evaluation-unjudged-candidate"),
        (facts.full_precision >= Decimal("0.80"), "ranking-regression"),
        (
            facts.full_ndcg - facts.lexical_ndcg >= Decimal("0.03"),
            "lexical-baseline-drift",
        ),
        (
            facts.lexical_precision - facts.full_precision <= Decimal("0.01"),
            "lexical-baseline-drift",
        ),
        (facts.success_output_truthful, "misleading-success-output"),
    )
    _require(checks)


def validate_integrity_contract(facts: IntegrityContractFacts) -> None:
    """Reject leaked credentials or mutated source reference artifacts."""
    _require(
        (
            (facts.runtime_secret_matches == 0, "secret-runtime"),
            (facts.source_hashes_match, "source-mutation"),
        )
    )


def _require(checks: tuple[tuple[bool, str], ...]) -> None:
    for valid, reason in checks:
        if not valid:
            raise Todo15ContractError(reason)
