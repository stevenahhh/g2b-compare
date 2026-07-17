"""Strict external assessor, adjudication, and parser-gold validation."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel, TypeAdapter, ValidationError

from g2b_compare.errors import (
    E0CountError,
    E0HashError,
    E0MissingFileError,
    E0SchemaError,
)

from .e0_assessment_validation import AssessmentRows, validate_assessment
from .e0_source_validation import (
    load_source_export,
    validate_adjudication_source,
    validate_assessor_source,
    validate_gold_source,
    validate_parser_source,
)
from .e0_strict_models import (
    AdjudicationRow,
    AssessorRow,
    GoldRow,
    ParserGoldRow,
    StrictFile,
    StrictManifest,
)

PARSER_ROW_COUNT: Final = 500
PARSER_SPAN_COUNT: Final = 500
PARSER_SEMANTIC_COUNT: Final = 600
PARSER_NEGATIVE_COUNT: Final = 50
INDEPENDENT_IDENTITY_COUNT: Final = 3
PARSER_STRATUM_COUNT: Final = 10
EXPECTED_FILES: Final[dict[str, tuple[str, int | None]]] = {
    "adjudication.jsonl": ("adjudication-v1", None),
    "assessor-a.jsonl": ("assessor-a-v1", 2000),
    "assessor-b.jsonl": ("assessor-b-v1", 2000),
    "gold-v1.jsonl": ("gold-v1-v1", 2000),
    "parser-gold-v1.jsonl": ("parser-gold-v1-v1", 500),
}
ASSESSOR_ADAPTER = TypeAdapter(AssessorRow)
ADJUDICATION_ADAPTER = TypeAdapter(AdjudicationRow)
GOLD_ADAPTER = TypeAdapter(GoldRow)
PARSER_ADAPTER = TypeAdapter(ParserGoldRow)


@dataclass(frozen=True, slots=True)
class StrictValidationFacts:
    """Facts proven by successful strict package validation."""

    total_count: int
    file_count: int
    strata: dict[str, int]


def validate_strict_package(
    manifest_path: Path,
    manifest: StrictManifest,
    source_export_path: Path,
) -> StrictValidationFacts:
    """Validate the complete externally labeled strict prerequisite."""
    identities = {*manifest.assessor_ids, manifest.adjudicator_id}
    if len(identities) != INDEPENDENT_IDENTITY_COUNT:
        raise E0SchemaError(manifest_path, "assessor identities are not independent")
    if manifest.label_scale != (0, 1, 2, 3):
        raise E0SchemaError(manifest_path, "label scale mismatch")
    if set(manifest.files) != set(EXPECTED_FILES):
        raise E0SchemaError(manifest_path, "strict file set mismatch")
    payloads = {
        name: _verified_payload(manifest_path, name, manifest.files[name])
        for name in EXPECTED_FILES
    }
    assessor_a = _rows(
        manifest_path.parent / "assessor-a.jsonl",
        payloads["assessor-a.jsonl"],
        ASSESSOR_ADAPTER,
    )
    assessor_b = _rows(
        manifest_path.parent / "assessor-b.jsonl",
        payloads["assessor-b.jsonl"],
        ASSESSOR_ADAPTER,
    )
    adjudication = _rows(
        manifest_path.parent / "adjudication.jsonl",
        payloads["adjudication.jsonl"],
        ADJUDICATION_ADAPTER,
    )
    gold = _rows(
        manifest_path.parent / "gold-v1.jsonl",
        payloads["gold-v1.jsonl"],
        GOLD_ADAPTER,
    )
    parser = _rows(
        manifest_path.parent / "parser-gold-v1.jsonl",
        payloads["parser-gold-v1.jsonl"],
        PARSER_ADAPTER,
    )
    source = load_source_export(source_export_path, manifest_path, manifest)
    validate_assessor_source(source, assessor_a, "a")
    validate_assessor_source(source, assessor_b, "b")
    validate_adjudication_source(source, adjudication)
    validate_gold_source(source, gold)
    validate_parser_source(source, parser)
    assessment = AssessmentRows(assessor_a, assessor_b, adjudication, gold)
    validate_assessment(manifest, assessment)
    strata = _validate_parser(parser)
    return StrictValidationFacts(6_500 + len(adjudication), 5, strata)


def _verified_payload(manifest_path: Path, name: str, declared: StrictFile) -> bytes:
    expected_schema, expected_count = EXPECTED_FILES[name]
    if declared.schema_version != expected_schema:
        raise E0SchemaError(manifest_path, f"{name} schema mismatch")
    file_path = manifest_path.parent / name
    if not file_path.is_file():
        raise E0MissingFileError(file_path)
    payload = file_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != declared.sha256:
        raise E0HashError(file_path, declared.sha256, digest)
    count = len(payload.splitlines())
    if count != declared.record_count:
        raise E0CountError(name, declared.record_count, count)
    if expected_count is not None and count != expected_count:
        raise E0CountError(name, expected_count, count)
    if len(payload) != declared.size:
        scope = f"{name}:bytes"
        raise E0CountError(scope, declared.size, len(payload))
    return payload


def _rows[T: BaseModel](
    path: Path, payload: bytes, adapter: TypeAdapter[T]
) -> tuple[T, ...]:
    output: list[T] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        try:
            output.append(adapter.validate_json(line))
        except ValidationError as error:
            detail = f"row {line_number} label/schema: {error}"
            raise E0SchemaError(path, detail) from None
    return tuple(output)


def _validate_parser(rows: tuple[ParserGoldRow, ...]) -> dict[str, int]:
    row_ids = {row.row_id for row in rows}
    if len(row_ids) != PARSER_ROW_COUNT:
        scope = "parser-rows"
        raise E0CountError(scope, PARSER_ROW_COUNT, len(row_ids))
    for row in rows:
        _validate_parser_row(row)
    spans = sum(len(row.spans) for row in rows)
    semantics = sum(len(span.semantics) for row in rows for span in row.spans)
    negative = sum(row.stratum == "zero-negative-unsupported" for row in rows)
    expected = (PARSER_SPAN_COUNT, PARSER_SEMANTIC_COUNT, PARSER_NEGATIVE_COUNT)
    if (spans, semantics, negative) != expected:
        raise E0SchemaError(Path("parser-gold-v1.jsonl"), "parser aggregate mismatch")
    strata = dict(Counter(row.stratum for row in rows))
    if (
        set(strata.values()) != {PARSER_NEGATIVE_COUNT}
        or len(strata) != PARSER_STRATUM_COUNT
    ):
        raise E0SchemaError(Path("parser-gold-v1.jsonl"), "parser stratum mismatch")
    return strata


def _validate_parser_row(row: ParserGoldRow) -> None:
    expected_spans = (
        0
        if row.stratum == "zero-negative-unsupported"
        else 2
        if row.stratum == "compound-mixed"
        else 1
    )
    if len(row.spans) != expected_spans or row.supported != (expected_spans > 0):
        raise E0SchemaError(Path("parser-gold-v1.jsonl"), "parser span shape mismatch")
    for span in row.spans:
        raw_bytes = row.text.encode()[span.start_byte : span.end_byte]
        if raw_bytes.decode() != span.raw:
            raise E0SchemaError(
                Path("parser-gold-v1.jsonl"), "parser byte range mismatch"
            )
        expected_semantics = 3 if row.stratum == "dimension" else 1
        if len(span.semantics) != expected_semantics:
            raise E0SchemaError(
                Path("parser-gold-v1.jsonl"), "parser semantic shape mismatch"
            )
