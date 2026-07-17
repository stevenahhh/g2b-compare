"""Validation for immutable unlabeled E0 export packages."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.errors import (
    E0CountError,
    E0HashError,
    E0MissingFileError,
    E0SchemaError,
    E0StratumError,
)

from .e0_export_models import (
    ANCHOR_COUNT,
    ASSESSOR_ADAPTER,
    CANDIDATE_COUNT,
    EXPECTED_FILES,
    PAIR_COUNT,
    PARSER_ADAPTER,
    PARSER_NEGATIVE_COUNT,
    PARSER_SEMANTIC_COUNT,
    PARSER_SPAN_COUNT,
    POOL_ADAPTER,
    AssessorTemplateRow,
    ExportFile,
    ExportManifest,
    ExportValidationFacts,
    ParserTemplateRow,
    PoolRow,
)


def validate_export_package(
    manifest_path: Path,
    manifest: ExportManifest,
) -> ExportValidationFacts:
    """Validate hashes and every machine-consumed export invariant."""
    if set(manifest.files) != set(EXPECTED_FILES):
        raise E0SchemaError(manifest_path, "export file set mismatch")
    payloads = {
        name: _verified_payload(manifest_path, name, manifest.files[name])
        for name in EXPECTED_FILES
    }
    pool = _rows(
        manifest_path.parent / "pool.jsonl", payloads["pool.jsonl"], POOL_ADAPTER
    )
    assessor_a = _rows(
        manifest_path.parent / "assessor-a.template.jsonl",
        payloads["assessor-a.template.jsonl"],
        ASSESSOR_ADAPTER,
    )
    assessor_b = _rows(
        manifest_path.parent / "assessor-b.template.jsonl",
        payloads["assessor-b.template.jsonl"],
        ASSESSOR_ADAPTER,
    )
    parser = _rows(
        manifest_path.parent / "parser.template.jsonl",
        payloads["parser.template.jsonl"],
        PARSER_ADAPTER,
    )
    _validate_pool(manifest, pool)
    _validate_assessors(pool, assessor_a, assessor_b)
    _validate_parser(manifest, parser, payloads["parser.template.jsonl"])
    return ExportValidationFacts(6500, 4, dict(manifest.strata))


def _verified_payload(manifest_path: Path, name: str, declared: ExportFile) -> bytes:
    expected_schema, expected_count = EXPECTED_FILES[name]
    if declared.schema_version != expected_schema:
        raise E0SchemaError(manifest_path, f"{name} schema mismatch")
    file_path = manifest_path.parent / name
    if not file_path.is_file():
        raise E0MissingFileError(file_path)
    payload = file_path.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != declared.sha256:
        raise E0HashError(file_path, declared.sha256, actual_hash)
    actual_count = len(payload.splitlines())
    if actual_count != declared.record_count or actual_count != expected_count:
        raise E0CountError(name, expected_count, actual_count)
    if len(payload) != declared.size:
        scope = f"{name}:bytes"
        raise E0CountError(scope, declared.size, len(payload))
    return payload


def _rows[T: BaseModel](
    path: Path, payload: bytes, adapter: TypeAdapter[T]
) -> tuple[T, ...]:
    parsed: list[T] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        try:
            parsed.append(adapter.validate_json(line))
        except ValidationError as error:
            detail = f"row {line_number}: {error}"
            raise E0SchemaError(path, detail) from None
    return tuple(parsed)


def _validate_pool(manifest: ExportManifest, rows: tuple[PoolRow, ...]) -> None:
    pairs = {(row.anchor_id, row.candidate_id) for row in rows}
    anchors = {row.anchor_id for row in rows}
    if len(pairs) != PAIR_COUNT or len(anchors) != ANCHOR_COUNT:
        scope = "pool"
        raise E0CountError(scope, PAIR_COUNT, len(pairs))
    per_anchor = Counter(row.anchor_id for row in rows)
    if set(per_anchor.values()) != {CANDIDATE_COUNT}:
        scope = "pool-per-anchor"
        raise E0CountError(scope, CANDIDATE_COUNT, min(per_anchor.values()))
    group_rows = Counter(_category_key(row) for row in rows)
    group_anchors: dict[str, set[str]] = {}
    for row in rows:
        group = _category_key(row)
        group_anchors.setdefault(group, set()).add(row.anchor_id)
    actual_groups = {
        group: (len(group_anchors[group]), count) for group, count in group_rows.items()
    }
    expected_groups = {
        group: (receipt.anchor_count, receipt.pair_count)
        for group, receipt in manifest.group_counts.items()
    }
    if actual_groups != expected_groups:
        raise E0SchemaError(Path("manifest.json"), "group counts mismatch")
    if any(
        row.source_index_sha != manifest.release.index_artifact_sha
        or row.source_materialization_sha != manifest.release.materialization_sha
        or row.source_release_bundle_sha != manifest.release.release_bundle_sha
        or row.ranking_version != manifest.release.ranking_version
        or row.split != manifest.group_counts[_category_key(row)].split
        for row in rows
    ):
        raise E0SchemaError(Path("manifest.json"), "pool source identity mismatch")
    if {
        group: receipt.split for group, receipt in manifest.group_counts.items()
    } != manifest.split_map:
        raise E0SchemaError(Path("manifest.json"), "group split map mismatch")
    actual_strata = dict(
        Counter({row.anchor_id: row.anchor_stratum for row in rows}.values())
    )
    if actual_strata != manifest.strata:
        scope = "export-pool"
        raise E0StratumError(scope, dict(manifest.strata), actual_strata)


def _validate_assessors(
    pool: tuple[PoolRow, ...],
    left: tuple[AssessorTemplateRow, ...],
    right: tuple[AssessorTemplateRow, ...],
) -> None:
    expected = {(row.anchor_id, row.candidate_id) for row in pool}
    for slot, rows in (("a", left), ("b", right)):
        actual = {(row.anchor_id, row.candidate_id) for row in rows}
        if actual != expected or any(row.assessor_slot != slot for row in rows):
            detail = f"assessor {slot} mismatch"
            raise E0SchemaError(Path("manifest.json"), detail)
        ordinals: dict[str, set[int]] = {}
        for row in rows:
            ordinals.setdefault(row.anchor_id, set()).add(row.blinded_ordinal)
        if any(
            values != set(range(1, CANDIDATE_COUNT + 1)) for values in ordinals.values()
        ):
            raise E0SchemaError(Path("manifest.json"), "blinded order mismatch")


def _validate_parser(
    manifest: ExportManifest, rows: tuple[ParserTemplateRow, ...], payload: bytes
) -> None:
    spans = sum(row.expected_span_count for row in rows)
    semantics = sum(row.expected_semantic_result_count for row in rows)
    negative = sum(row.stratum == "zero-negative-unsupported" for row in rows)
    if spans != manifest.counts.parser_positive_spans:
        scope = "parser-positive-spans"
        raise E0CountError(scope, PARSER_SPAN_COUNT, spans)
    if semantics != manifest.counts.parser_semantic_results:
        scope = "parser-semantic-results"
        raise E0CountError(scope, PARSER_SEMANTIC_COUNT, semantics)
    if negative != manifest.counts.parser_negative_rows:
        scope = "parser-negative-rows"
        raise E0CountError(scope, PARSER_NEGATIVE_COUNT, negative)
    if any(row.spans for row in rows):
        raise E0SchemaError(Path("manifest.json"), "template contains labels")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != manifest.parser_template_sha256:
        raise E0HashError(
            Path("parser.template.jsonl"), manifest.parser_template_sha256, digest
        )


def _category_key(row: PoolRow) -> str:
    category: dict[str, JsonValue] = row.category_tuple.model_dump()
    return canonical_json(category)
