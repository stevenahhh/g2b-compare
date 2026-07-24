"""Typed, fail-closed loading for strict evaluation predictions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal  # noqa: TC003 -- Pydantic resolves this field at runtime.
from typing import TYPE_CHECKING, ClassVar, override

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .e0_strict_models import GoldRow, ParserGoldRow, ParserSpan

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class EvaluationArtifactError(Exception):
    """Identify an unusable evaluator input without guessing missing values."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


class RankingPrediction(BaseModel):
    """One score produced for a candidate in the exported judged pool."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    anchor_id: str
    candidate_id: str
    score: Decimal | None
    category_match: bool


class ParserPrediction(BaseModel):
    """All parser spans predicted for one exported source row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    row_id: str
    spans: tuple[ParserSpan, ...]


@dataclass(frozen=True, slots=True)
class EvaluationArtifacts:
    """Validated external gold and independently generated prediction rows."""

    gold: tuple[GoldRow, ...]
    parser_gold: tuple[ParserGoldRow, ...]
    full_v1: tuple[RankingPrediction, ...]
    lexical_only: tuple[RankingPrediction, ...]
    parser_predictions: tuple[ParserPrediction, ...]


def load_evaluation_artifacts(
    gold_path: Path,
    parser_gold_path: Path,
    full_v1_path: Path,
    lexical_only_path: Path,
    parser_predictions_path: Path,
) -> EvaluationArtifacts:
    """Parse actual JSONL artifacts using closed schemas."""
    return EvaluationArtifacts(
        _load_jsonl(gold_path, TypeAdapter(GoldRow)),
        _load_jsonl(parser_gold_path, TypeAdapter(ParserGoldRow)),
        _load_jsonl(full_v1_path, TypeAdapter(RankingPrediction)),
        _load_jsonl(lexical_only_path, TypeAdapter(RankingPrediction)),
        _load_jsonl(parser_predictions_path, TypeAdapter(ParserPrediction)),
    )


def _load_jsonl[Model: BaseModel](
    path: Path,
    adapter: TypeAdapter[Model],
) -> tuple[Model, ...]:
    if not path.is_file():
        detail = f"missing evaluation artifact: {path.name}"
        raise EvaluationArtifactError(detail)
    rows: list[Model] = []
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            rows.append(adapter.validate_json(line))
        except ValidationError as error:
            detail = f"{path.name}: row {line_number}: {error}"
            raise EvaluationArtifactError(detail) from None
    return tuple(rows)
