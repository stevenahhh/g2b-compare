"""Cross-assessor, adjudication, and finalized-gold validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from g2b_compare.errors import E0CountError, E0SchemaError

if TYPE_CHECKING:
    from .e0_strict_models import (
        AdjudicationRow,
        AssessorRow,
        GoldRow,
        StrictManifest,
    )

ANCHOR_COUNT: Final = 200
PAIR_COUNT: Final = 2_000
CANDIDATE_COUNT: Final = 10
Pair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class AssessmentRows:
    """All ordered assessor, adjudication, and gold rows."""

    left: tuple[AssessorRow, ...]
    right: tuple[AssessorRow, ...]
    adjudications: tuple[AdjudicationRow, ...]
    gold: tuple[GoldRow, ...]


def validate_assessment(manifest: StrictManifest, rows: AssessmentRows) -> None:
    """Validate ordered assessor provenance and derived final labels."""
    left_map = {_pair(row): row for row in rows.left}
    right_map = {_pair(row): row for row in rows.right}
    if len(left_map) != PAIR_COUNT or set(left_map) != set(right_map):
        scope = "assessor-pairs"
        raise E0CountError(scope, PAIR_COUNT, len(left_map))
    if any(row.assessor_id != manifest.assessor_ids[0] for row in rows.left) or any(
        row.assessor_id != manifest.assessor_ids[1] for row in rows.right
    ):
        raise E0SchemaError(Path("manifest.json"), "assessor identity drift")
    _validate_blinding(rows.left)
    _validate_blinding(rows.right)
    disagreements = {
        pair
        for pair in left_map
        if left_map[pair].label_0_3 != right_map[pair].label_0_3
    }
    adjudication_map = _validate_adjudications(
        manifest, rows.adjudications, left_map, right_map, disagreements
    )
    gold_map = {_pair(row): row for row in rows.gold}
    if set(gold_map) != set(left_map):
        scope = "gold-pairs"
        raise E0CountError(scope, PAIR_COUNT, len(gold_map))
    for pair, gold_row in gold_map.items():
        left_label = left_map[pair].label_0_3
        right_label = right_map[pair].label_0_3
        final = (
            left_label
            if left_label == right_label
            else adjudication_map[pair].final_label
        )
        if gold_row.final_label != final:
            raise E0SchemaError(Path("gold-v1.jsonl"), "final label mismatch")
    anchors_by_split: dict[str, set[str]] = {}
    for row in rows.gold:
        anchors_by_split.setdefault(row.split, set()).add(row.anchor_id)
    actual_splits = {key: len(value) for key, value in anchors_by_split.items()}
    if actual_splits != manifest.split_counts:
        raise E0SchemaError(Path("gold-v1.jsonl"), "split count mismatch")


def _validate_adjudications(
    manifest: StrictManifest,
    adjudications: tuple[AdjudicationRow, ...],
    left: dict[Pair, AssessorRow],
    right: dict[Pair, AssessorRow],
    disagreements: set[Pair],
) -> dict[Pair, AdjudicationRow]:
    actual = {_pair(row): row for row in adjudications}
    if len(actual) != len(adjudications) or set(actual) != disagreements:
        raise E0SchemaError(Path("manifest.json"), "adjudication set mismatch")
    if len(adjudications) != manifest.counts.adjudications:
        raise E0SchemaError(Path("manifest.json"), "adjudication count mismatch")
    for pair, row in actual.items():
        if row.adjudicator_id != manifest.adjudicator_id:
            raise E0SchemaError(
                Path("adjudication.jsonl"), "adjudicator identity drift"
            )
        if row.label_a != left[pair].label_0_3 or row.label_b != right[pair].label_0_3:
            raise E0SchemaError(
                Path("adjudication.jsonl"), "adjudication label provenance mismatch"
            )
    return actual


def _validate_blinding(rows: tuple[AssessorRow, ...]) -> None:
    ordinals: dict[str, set[int]] = {}
    for row in rows:
        ordinals.setdefault(row.anchor_id, set()).add(row.blinded_ordinal)
    if len(ordinals) != ANCHOR_COUNT or any(
        values != set(range(1, CANDIDATE_COUNT + 1)) for values in ordinals.values()
    ):
        raise E0SchemaError(Path("assessor.jsonl"), "blinded order mismatch")


def _pair(row: AssessorRow | AdjudicationRow | GoldRow) -> Pair:
    return (row.anchor_id, row.candidate_id)
