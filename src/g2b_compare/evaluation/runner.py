"""Fail-closed execution and thresholds for external held-out evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, override

from .e0_schema import validate_e0_package
from .metrics import (
    ParserUnit,
    RankingItem,
    macro_ranking_metrics,
    parser_metrics,
    ranking_metrics,
)
from .runner_artifacts import (
    EvaluationArtifactError,
    ParserPrediction,
    RankingPrediction,
    load_evaluation_artifacts,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .e0_strict_models import GoldRow, ParserGoldRow, ParserSemantic, ParserSpan
    from .metrics import ParserMetrics, RankingMetrics

PARSER_PRECISION_MIN: Final = Decimal("0.98")
PARSER_RECALL_MIN: Final = Decimal("0.90")
FULL_PRECISION_MIN: Final = Decimal("0.80")
NDCG_LIFT_MIN: Final = Decimal("0.03")
LEXICAL_PRECISION_DELTA_MAX: Final = Decimal("0.01")
DETERMINISM_REQUIRED: Final = Decimal(1)
HELD_OUT_ANCHORS: Final = 40
CANDIDATES_PER_ANCHOR: Final = 10


@dataclass(frozen=True, slots=True)
class EvaluationThresholdError(Exception):
    """Name the first strict held-out requirement that failed."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class HeldOutReport:
    """All metrics required to decide the strict release gate."""

    anchor_count: int
    category_leakage: int
    null_slot_rate: Decimal
    judged_pool_determinism: Decimal
    full_v1: RankingMetrics
    lexical_only: RankingMetrics
    parser: ParserMetrics


@dataclass(frozen=True, slots=True)
class StrictEvaluationPaths:
    """All external and generated artifacts consumed by one evaluation run."""

    manifest: Path
    source_export: Path
    full_v1_predictions: Path
    lexical_predictions: Path
    parser_predictions: Path


def run_strict_evaluation(paths: StrictEvaluationPaths) -> HeldOutReport:
    """Validate external gold, read predictions, and evaluate only test splits."""
    validation = validate_e0_package(
        paths.manifest,
        strict=True,
        source_export=paths.source_export,
    )
    if validation.schema_version != "e0-strict-v1":
        detail = "external evaluation is not strict"
        raise EvaluationArtifactError(detail)
    root = paths.manifest.parent
    artifacts = load_evaluation_artifacts(
        root / "gold-v1.jsonl",
        root / "parser-gold-v1.jsonl",
        paths.full_v1_predictions,
        paths.lexical_predictions,
        paths.parser_predictions,
    )
    gold_by_pair = {(row.anchor_id, row.candidate_id): row for row in artifacts.gold}
    if len(gold_by_pair) != len(artifacts.gold):
        detail = "duplicate gold pair"
        raise EvaluationArtifactError(detail)
    _require_prediction_pool("full-v1", artifacts.full_v1, gold_by_pair)
    _require_prediction_pool("lexical-only", artifacts.lexical_only, gold_by_pair)
    parser_gold_by_id = {row.row_id: row for row in artifacts.parser_gold}
    parser_prediction_by_id = {row.row_id: row for row in artifacts.parser_predictions}
    if len(parser_prediction_by_id) != len(artifacts.parser_predictions):
        detail = "duplicate parser prediction row"
        raise EvaluationArtifactError(detail)
    if set(parser_prediction_by_id) != set(parser_gold_by_id):
        detail = "parser prediction pool mismatch"
        raise EvaluationArtifactError(detail)

    held_out_gold = tuple(row for row in artifacts.gold if row.split == "test")
    anchor_ids = sorted({row.anchor_id for row in held_out_gold}, key=str.encode)
    if len(anchor_ids) != HELD_OUT_ANCHORS:
        detail = "held-out anchor count"
        raise EvaluationArtifactError(detail)
    labels = {
        (row.anchor_id, row.candidate_id): row.final_label for row in held_out_gold
    }
    full_metrics, category_leakage, null_slots = _ranking_report(
        artifacts.full_v1, anchor_ids, labels
    )
    lexical_metrics, _, _ = _ranking_report(artifacts.lexical_only, anchor_ids, labels)
    held_out_parser_gold = tuple(
        row for row in artifacts.parser_gold if row.split == "test"
    )
    parser_gold_units = _parser_units(held_out_parser_gold)
    parser_prediction_units = _prediction_units(
        held_out_parser_gold, parser_prediction_by_id
    )
    report = HeldOutReport(
        anchor_count=len(anchor_ids),
        category_leakage=category_leakage,
        null_slot_rate=Decimal(null_slots) / Decimal(HELD_OUT_ANCHORS * 3),
        judged_pool_determinism=Decimal(1),
        full_v1=full_metrics,
        lexical_only=lexical_metrics,
        parser=parser_metrics(parser_gold_units, parser_prediction_units),
    )
    return validate_held_out(report)


def _require_prediction_pool(
    name: str,
    rows: tuple[RankingPrediction, ...],
    gold: dict[tuple[str, str], GoldRow],
) -> None:
    pairs = {(row.anchor_id, row.candidate_id) for row in rows}
    if len(pairs) != len(rows):
        detail = f"{name} duplicate candidate"
        raise EvaluationArtifactError(detail)
    if pairs != set(gold):
        detail = f"{name} judged pool mismatch"
        raise EvaluationArtifactError(detail)


def _ranking_report(
    rows: tuple[RankingPrediction, ...],
    anchor_ids: list[str],
    labels: dict[tuple[str, str], int],
) -> tuple[RankingMetrics, int, int]:
    by_anchor: dict[str, list[RankingPrediction]] = {}
    for row in rows:
        if row.anchor_id in anchor_ids:
            by_anchor.setdefault(row.anchor_id, []).append(row)
    per_anchor: list[RankingMetrics] = []
    category_leakage = 0
    null_slots = 0
    for anchor_id in anchor_ids:
        candidates = by_anchor.get(anchor_id, [])
        if len(candidates) != CANDIDATES_PER_ANCHOR:
            detail = "held-out candidate count"
            raise EvaluationArtifactError(detail)
        ordered = sorted(
            candidates,
            key=lambda row: (
                row.score is None,
                -(row.score or Decimal(0)),
                row.candidate_id.encode(),
            ),
        )
        category_leakage += sum(not row.category_match for row in ordered[:3])
        null_slots += sum(row.score is None for row in ordered[:3])
        per_anchor.append(
            ranking_metrics(
                tuple(
                    RankingItem(
                        row.candidate_id,
                        labels[(row.anchor_id, row.candidate_id)],
                        row.score,
                    )
                    for row in candidates
                )
            )
        )
    return macro_ranking_metrics(tuple(per_anchor)), category_leakage, null_slots


def _parser_units(rows: tuple[ParserGoldRow, ...]) -> tuple[ParserUnit, ...]:
    return tuple(
        _parser_unit(row.row_id, span, semantic)
        for row in rows
        for span in row.spans
        for semantic in span.semantics
    )


def _prediction_units(
    gold_rows: tuple[ParserGoldRow, ...],
    predictions: dict[str, ParserPrediction],
) -> tuple[ParserUnit, ...]:
    return tuple(
        _parser_unit(row.row_id, span, semantic)
        for row in gold_rows
        for span in predictions[row.row_id].spans
        for semantic in span.semantics
    )


def _parser_unit(
    row_id: str,
    span: ParserSpan,
    semantic: ParserSemantic,
) -> ParserUnit:
    return ParserUnit(
        row_id,
        span.start_byte,
        span.end_byte,
        (
            semantic.value_decimal,
            semantic.canonical_unit,
            semantic.dimension,
            semantic.attribute_key,
            semantic.relation,
            semantic.lower,
            semantic.upper,
        ),
    )


def validate_held_out(report: HeldOutReport) -> HeldOutReport:
    """Return the report only when every strict threshold passes."""
    failures = (
        (report.anchor_count != HELD_OUT_ANCHORS, "held-out anchor count"),
        (report.category_leakage != 0, "category leakage"),
        (
            report.judged_pool_determinism != DETERMINISM_REQUIRED,
            "judged pool determinism",
        ),
        (report.null_slot_rate != 0, "null slot rate"),
        (report.parser.precision < PARSER_PRECISION_MIN, "parser precision"),
        (report.parser.recall < PARSER_RECALL_MIN, "parser recall"),
        (report.full_v1.precision_at_3 < FULL_PRECISION_MIN, "full-v1 precision"),
        (
            report.full_v1.ndcg_at_3 - report.lexical_only.ndcg_at_3 < NDCG_LIFT_MIN,
            "lexical precision and nDCG lift",
        ),
        (
            report.lexical_only.precision_at_3 - report.full_v1.precision_at_3
            > LEXICAL_PRECISION_DELTA_MAX,
            "lexical precision regression",
        ),
    )
    for failed, reason in failures:
        if failed:
            raise EvaluationThresholdError(reason)
    return report
