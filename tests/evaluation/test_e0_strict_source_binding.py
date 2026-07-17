"""Frozen export binding and disagreement contracts for strict E0 gold."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.errors import E0SchemaError
from g2b_compare.evaluation.e0_export import export_e0
from g2b_compare.evaluation.e0_schema import validate_e0_package

from .e0_fixture import release_fixture
from .e0_strict_fixture import write_strict_package

if TYPE_CHECKING:
    from pathlib import Path

JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


def test_strict_gold_binds_to_frozen_export_and_real_disagreement(
    tmp_path: Path,
) -> None:
    # Given: strict gold derived from one exact export with one assessor disagreement
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(
        tmp_path / "strict",
        source,
        disagreement_count=1,
    )

    # When: strict validation joins every gold row to that source
    report = validate_e0_package(manifest, strict=True, source_export=source)

    # Then: the derived adjudication contributes exactly one validated record
    assert report.total_count == 6_501


def test_strict_gold_rejects_unrelated_assessor_corpus(tmp_path: Path) -> None:
    # Given: A-* judgments claim provenance from an unrelated P-* export
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source, unrelated=True)

    # When/Then: source membership fails closed
    with pytest.raises(E0SchemaError, match="source"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_strict_gold_rejects_source_manifest_sha_drift(tmp_path: Path) -> None:
    # Given: the strict manifest names a different source-export digest
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)
    data = JSON_ADAPTER.validate_json(manifest.read_bytes())
    source_identity = data["source_export"]
    assert isinstance(source_identity, dict)
    source_identity["manifest_sha256"] = "0" * 64
    _ = manifest.write_text(canonical_json(data) + "\n", encoding="utf-8")

    # When/Then: the exact source receipt is required
    with pytest.raises(E0SchemaError, match=r"source.*SHA"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_strict_gold_rejects_source_ranking_identity_drift(tmp_path: Path) -> None:
    # Given: strict gold claims a ranking identity absent from the frozen export
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)
    data = JSON_ADAPTER.validate_json(manifest.read_bytes())
    source_identity = data["source_export"]
    assert isinstance(source_identity, dict)
    source_identity["ranking_version"] = "drift"
    _ = manifest.write_text(canonical_json(data) + "\n", encoding="utf-8")

    # When/Then: release and ranking identities must match the source receipt
    with pytest.raises(E0SchemaError, match="source export identity"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_strict_gold_rejects_parser_text_not_in_source_template(
    tmp_path: Path,
) -> None:
    # Given: parser gold text drifts while its local file receipt remains valid
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)
    parser = manifest.parent / "parser-gold-v1.jsonl"
    rows = parser.read_text(encoding="utf-8").splitlines()
    first = JSON_ADAPTER.validate_json(rows[0])
    first["text"] = str(first["text"]) + " drift"
    rows[0] = canonical_json(first)
    _rewrite_declared(manifest, parser, ("\n".join(rows) + "\n").encode())

    # When/Then: parser row_id/text/split must match the frozen template
    with pytest.raises(E0SchemaError, match="parser source"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_disagreement_requires_one_adjudication_row(tmp_path: Path) -> None:
    # Given: one assessor disagreement but an empty adjudication file
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(
        tmp_path / "strict",
        source,
        disagreement_count=1,
    )
    adjudication = manifest.parent / "adjudication.jsonl"
    _rewrite_declared(manifest, adjudication, b"")

    # When/Then: every disagreement requires exactly one row
    with pytest.raises(E0SchemaError, match="adjudication set"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_disagreement_requires_exact_adjudication_label_provenance(
    tmp_path: Path,
) -> None:
    # Given: an adjudication copies neither ordered assessor-A label
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(
        tmp_path / "strict",
        source,
        disagreement_count=1,
    )
    adjudication = manifest.parent / "adjudication.jsonl"
    row = JSON_ADAPTER.validate_json(adjudication.read_bytes())
    row["label_a"] = (int(str(row["label_a"])) + 1) % 4
    _rewrite_declared(manifest, adjudication, (canonical_json(row) + "\n").encode())

    # When/Then: adjudicator provenance is derived from the assessor pair
    with pytest.raises(E0SchemaError, match="adjudication label provenance"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_disagreement_requires_manifest_adjudicator_identity(tmp_path: Path) -> None:
    # Given: a disagreement is adjudicated under an assessor identity
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(
        tmp_path / "strict",
        source,
        disagreement_count=1,
    )
    adjudication = manifest.parent / "adjudication.jsonl"
    row = JSON_ADAPTER.validate_json(adjudication.read_bytes())
    row["adjudicator_id"] = "alpha"
    _rewrite_declared(manifest, adjudication, (canonical_json(row) + "\n").encode())

    # When/Then: provenance must equal the independent manifest adjudicator
    with pytest.raises(E0SchemaError, match="adjudicator identity"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_assessor_split_must_match_source_pool(tmp_path: Path) -> None:
    # Given: one otherwise valid assessor row is assigned to another split
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)
    assessor = manifest.parent / "assessor-a.jsonl"
    rows = assessor.read_text(encoding="utf-8").splitlines()
    first = JSON_ADAPTER.validate_json(rows[0])
    first["split"] = "test" if first["split"] != "test" else "train"
    rows[0] = canonical_json(first)
    _rewrite_declared(manifest, assessor, ("\n".join(rows) + "\n").encode())

    # When/Then: assessor split identity is joined to the frozen pool
    with pytest.raises(E0SchemaError, match="source assessor row"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def test_identical_assessors_require_zero_adjudications(tmp_path: Path) -> None:
    # Given: identical assessors but one fabricated adjudication row
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)
    assessor = manifest.parent / "assessor-a.jsonl"
    assessment = JSON_ADAPTER.validate_json(assessor.read_text().splitlines()[0])
    adjudication = manifest.parent / "adjudication.jsonl"
    row: dict[str, JsonValue] = {
        "adjudicator_id": "gamma",
        "anchor_id": assessment["anchor_id"],
        "candidate_id": assessment["candidate_id"],
        "final_label": assessment["label_0_3"],
        "label_a": assessment["label_0_3"],
        "label_b": assessment["label_0_3"],
        "reason": "fabricated",
        "split": assessment["split"],
    }
    _rewrite_declared(manifest, adjudication, (canonical_json(row) + "\n").encode())

    # When/Then: adjudication count is derived as zero
    with pytest.raises(E0SchemaError, match="adjudication set"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)


def _source_export(root: Path) -> Path:
    _ = export_e0(release_fixture(), root, seed="20260714")
    return root / "manifest.json"


def _rewrite_declared(manifest_path: Path, file_path: Path, payload: bytes) -> None:
    _ = file_path.write_bytes(payload)
    manifest = JSON_ADAPTER.validate_json(manifest_path.read_bytes())
    files = manifest["files"]
    assert isinstance(files, dict)
    declaration = files[file_path.name]
    assert isinstance(declaration, dict)
    declaration["record_count"] = len(payload.splitlines())
    declaration["sha256"] = hashlib.sha256(payload).hexdigest()
    declaration["size"] = len(payload)
    _ = manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
