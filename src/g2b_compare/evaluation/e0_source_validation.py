"""Validation joins from strict gold to one frozen unlabeled export."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from g2b_compare.errors import E0MissingFileError, E0SchemaError

from .e0_export_models import (
    ASSESSOR_ADAPTER,
    PARSER_ADAPTER,
    POOL_ADAPTER,
    AssessorTemplateRow,
    ExportManifest,
    PoolRow,
)
from .e0_export_validation import validate_export_package
from .e0_strict_models import (
    AdjudicationRow,
    AssessorRow,
    GoldRow,
    ParserGoldRow,
    SourceExportIdentity,
    StrictManifest,
)

if TYPE_CHECKING:
    from g2b_compare.db.hashes import JsonValue

Pair = tuple[str, str]
Split = Literal["train", "validation", "test"]


@dataclass(frozen=True, slots=True)
class ParserSourceIdentity:
    """Source parser-template values that strict gold must preserve."""

    expected_semantics: int
    expected_spans: int
    split: Split
    stratum: str
    text: str


@dataclass(frozen=True, slots=True)
class SourceExportFacts:
    """Validated lookup maps from one exact source export."""

    assessor_a: dict[Pair, int]
    assessor_b: dict[Pair, int]
    pairs: dict[Pair, Split]
    parser: dict[str, ParserSourceIdentity]


def load_source_export(
    source_manifest_path: Path,
    strict_manifest_path: Path,
    strict_manifest: StrictManifest,
) -> SourceExportFacts:
    """Validate the source receipt and return exact row identities."""
    if not source_manifest_path.is_file():
        raise E0MissingFileError(source_manifest_path)
    payload = source_manifest_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != strict_manifest.source_export.manifest_sha256:
        raise E0SchemaError(strict_manifest_path, "source export manifest SHA mismatch")
    try:
        manifest = ExportManifest.model_validate_json(payload)
    except ValidationError as error:
        raise E0SchemaError(source_manifest_path, str(error)) from None
    _ = validate_export_package(source_manifest_path, manifest)
    _validate_source_identity(strict_manifest_path, strict_manifest, manifest, digest)
    root = source_manifest_path.parent
    pool = _rows(root / "pool.jsonl", POOL_ADAPTER)
    assessor_a = _rows(root / "assessor-a.template.jsonl", ASSESSOR_ADAPTER)
    assessor_b = _rows(root / "assessor-b.template.jsonl", ASSESSOR_ADAPTER)
    parser = _rows(root / "parser.template.jsonl", PARSER_ADAPTER)
    return SourceExportFacts(
        _assessor_map(assessor_a),
        _assessor_map(assessor_b),
        {_pair(row): row.split for row in pool},
        {
            row.row_id: ParserSourceIdentity(
                row.expected_semantic_result_count,
                row.expected_span_count,
                row.split,
                row.stratum,
                row.text,
            )
            for row in parser
        },
    )


def validate_assessor_source(
    source: SourceExportFacts,
    rows: tuple[AssessorRow, ...],
    slot: Literal["a", "b"],
) -> None:
    """Require assessor pairs, ordinals, and splits from one template slot."""
    expected = source.assessor_a if slot == "a" else source.assessor_b
    actual = {_pair(row): row for row in rows}
    if len(actual) != len(rows) or set(actual) != set(expected):
        raise E0SchemaError(Path("assessor.jsonl"), "source assessor pair mismatch")
    if any(
        row.blinded_ordinal != expected[pair] or row.split != source.pairs[pair]
        for pair, row in actual.items()
    ):
        raise E0SchemaError(Path("assessor.jsonl"), "source assessor row mismatch")


def validate_adjudication_source(
    source: SourceExportFacts,
    rows: tuple[AdjudicationRow, ...],
) -> None:
    """Require every adjudication pair and split to exist in the source pool."""
    if any(
        _pair(row) not in source.pairs or row.split != source.pairs.get(_pair(row))
        for row in rows
    ):
        raise E0SchemaError(Path("adjudication.jsonl"), "source adjudication mismatch")


def validate_gold_source(
    source: SourceExportFacts,
    rows: tuple[GoldRow, ...],
) -> None:
    """Require finalized pair membership and split from the source pool."""
    actual = {_pair(row): row for row in rows}
    if len(actual) != len(rows) or set(actual) != set(source.pairs):
        raise E0SchemaError(Path("gold-v1.jsonl"), "source gold pair mismatch")
    if any(row.split != source.pairs[pair] for pair, row in actual.items()):
        raise E0SchemaError(Path("gold-v1.jsonl"), "source gold split mismatch")


def validate_parser_source(
    source: SourceExportFacts,
    rows: tuple[ParserGoldRow, ...],
) -> None:
    """Require parser row identity and targets from the source template."""
    actual = {row.row_id: row for row in rows}
    if len(actual) != len(rows) or set(actual) != set(source.parser):
        raise E0SchemaError(Path("parser-gold-v1.jsonl"), "parser source row mismatch")
    for row_id, row in actual.items():
        expected = source.parser[row_id]
        semantic_count = sum(len(span.semantics) for span in row.spans)
        identity = (row.text, row.split, row.stratum)
        expected_identity = (expected.text, expected.split, expected.stratum)
        if identity != expected_identity:
            raise E0SchemaError(
                Path("parser-gold-v1.jsonl"), "parser source identity mismatch"
            )
        if (
            len(row.spans) != expected.expected_spans
            or semantic_count != expected.expected_semantics
        ):
            raise E0SchemaError(
                Path("parser-gold-v1.jsonl"), "parser source target mismatch"
            )


def _validate_source_identity(
    path: Path,
    strict: StrictManifest,
    source: ExportManifest,
    digest: str,
) -> None:
    values: dict[str, JsonValue] = source.release.model_dump()
    values["export_id"] = source.export_id
    values["manifest_sha256"] = digest
    values["parser_template_sha256"] = source.parser_template_sha256
    try:
        actual = SourceExportIdentity.model_validate(values)
    except ValidationError as error:
        raise E0SchemaError(path, f"source export identity schema: {error}") from None
    if actual != strict.source_export:
        raise E0SchemaError(path, "source export identity mismatch")
    if strict.seed != source.seed or strict.split_counts != source.split_counts:
        raise E0SchemaError(path, "source export selection mismatch")


def _rows[T: BaseModel](path: Path, adapter: TypeAdapter[T]) -> tuple[T, ...]:
    output: list[T] = []
    for line_number, line in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            output.append(adapter.validate_json(line))
        except ValidationError as error:
            detail = f"source row {line_number}: {error}"
            raise E0SchemaError(path, detail) from None
    return tuple(output)


def _assessor_map(rows: tuple[AssessorTemplateRow, ...]) -> dict[Pair, int]:
    return {_pair(row): row.blinded_ordinal for row in rows}


def _pair(
    row: PoolRow | AssessorTemplateRow | AssessorRow | AdjudicationRow | GoldRow,
) -> Pair:
    return (row.anchor_id, row.candidate_id)
