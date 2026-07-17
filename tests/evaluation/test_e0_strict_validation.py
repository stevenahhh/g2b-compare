"""Strict external assessor and parser-gold validation contracts."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter
from tools.validate_e0 import main as validate_main

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.errors import E0SchemaError
from g2b_compare.evaluation.e0_export import export_e0
from g2b_compare.evaluation.e0_schema import validate_e0_package

from .e0_fixture import release_fixture
from .e0_strict_fixture import write_strict_package

if TYPE_CHECKING:
    from pathlib import Path

JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


def test_strict_validator_accepts_complete_independent_gold(tmp_path: Path) -> None:
    # Given: exact assessor, gold, and parser prerequisite files
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "strict", source)

    # When: library and CLI strict boundaries validate the package
    report = validate_e0_package(manifest, strict=True, source_export=source)
    exit_code = validate_main(
        ["--strict", "--source-export", str(source), str(manifest)]
    )

    # Then: exact strict schema and typed success exit are reported
    assert report.schema_version == "e0-strict-v1"
    assert report.total_count == 6_500
    assert exit_code == 0
    assert validate_main(["--strict", str(manifest)]) == 2


def test_strict_validator_rejects_score_outside_zero_to_three(tmp_path: Path) -> None:
    # Given: one assessor label is changed to four with a matching file hash
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "score", source)
    assessor = manifest.parent / "assessor-a.jsonl"
    rows = assessor.read_text(encoding="utf-8").splitlines()
    first = JSON_ADAPTER.validate_json(rows[0])
    first["label_0_3"] = 4
    rows[0] = canonical_json(first)
    _rewrite_declared(manifest, assessor, ("\n".join(rows) + "\n").encode())

    # When/Then: score schema validation fails closed
    with pytest.raises(E0SchemaError, match="label"):
        _ = validate_e0_package(manifest, strict=True, source_export=source)
    assert (
        validate_main(["--strict", "--source-export", str(source), str(manifest)]) == 2
    )


def test_strict_validator_rejects_parser_span_shape_drift(tmp_path: Path) -> None:
    # Given: one positive parser row loses its required span with matching hash
    source = _source_export(tmp_path / "source")
    manifest = write_strict_package(tmp_path / "parser", source)
    parser = manifest.parent / "parser-gold-v1.jsonl"
    rows = parser.read_text(encoding="utf-8").splitlines()
    first = JSON_ADAPTER.validate_json(rows[0])
    first["spans"] = []
    rows[0] = canonical_json(first)
    _rewrite_declared(manifest, parser, ("\n".join(rows) + "\n").encode())

    # When/Then: parser structure validation fails rather than hash validation
    with pytest.raises(E0SchemaError, match="parser"):
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
    declaration["sha256"] = hashlib.sha256(payload).hexdigest()
    declaration["size"] = len(payload)
    _ = manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
