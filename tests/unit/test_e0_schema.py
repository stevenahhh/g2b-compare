from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter

from g2b_compare.errors import (
    E0CountError,
    E0HashError,
    E0MissingFileError,
    E0SchemaError,
    E0StratumError,
)
from g2b_compare.evaluation.e0_schema import validate_e0_package

if TYPE_CHECKING:
    from pathlib import Path


def write_e0_package(root: Path) -> tuple[Path, Path]:
    records_path = root / "records.jsonl"
    records = (
        '{"record_id":"r1","stratum":"positive","label":1}',
        '{"record_id":"r2","stratum":"negative","label":0}',
    )
    payload = ("\n".join(records) + "\n").encode()
    _ = records_path.write_bytes(payload)
    manifest = {
        "schema_version": "e0-v1",
        "total_count": 2,
        "strata": {"negative": 1, "positive": 1},
        "files": [
            {
                "path": "records.jsonl",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "record_count": 2,
                "strata": {"negative": 1, "positive": 1},
            }
        ],
    }
    manifest_path = root / "manifest.json"
    _ = manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, records_path


type JsonValue = str | int | list["JsonValue"] | dict[str, "JsonValue"]


def load_manifest(manifest_path: Path) -> dict[str, JsonValue]:
    return TypeAdapter(dict[str, JsonValue]).validate_json(manifest_path.read_bytes())


def test_e0_validator_accepts_immutable_external_package(tmp_path: Path) -> None:
    # Given: a valid externally authored E0 package
    manifest_path, records_path = write_e0_package(tmp_path)
    before = records_path.read_bytes()

    # When: the package is validated
    report = validate_e0_package(manifest_path)

    # Then: counts are reported and labels are not rewritten
    assert report.total_count == 2
    assert report.file_count == 1
    assert records_path.read_bytes() == before


def test_e0_validator_rejects_missing_declared_file(tmp_path: Path) -> None:
    # Given: a manifest whose declared file was removed
    manifest_path, records_path = write_e0_package(tmp_path)
    records_path.unlink()

    # When/Then: file presence validation fails
    with pytest.raises(E0MissingFileError, match="missing"):
        _ = validate_e0_package(manifest_path)


def test_e0_validator_rejects_bad_schema(tmp_path: Path) -> None:
    # Given: a manifest with an unsupported schema version
    manifest_path, _ = write_e0_package(tmp_path)
    manifest = load_manifest(manifest_path)
    manifest["schema_version"] = "e0-v0"
    _ = manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # When/Then: schema parsing fails at the boundary
    with pytest.raises(E0SchemaError, match="schema"):
        _ = validate_e0_package(manifest_path)


def test_e0_validator_rejects_bad_count(tmp_path: Path) -> None:
    # Given: a manifest with a false total count
    manifest_path, _ = write_e0_package(tmp_path)
    manifest = load_manifest(manifest_path)
    manifest["total_count"] = 3
    _ = manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # When/Then: exact count validation fails
    with pytest.raises(E0CountError, match="count"):
        _ = validate_e0_package(manifest_path)


def test_e0_validator_rejects_bad_stratum(tmp_path: Path) -> None:
    # Given: a manifest with biased aggregate strata
    manifest_path, _ = write_e0_package(tmp_path)
    manifest = load_manifest(manifest_path)
    manifest["strata"] = {"positive": 2}
    _ = manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # When/Then: exact stratum validation fails
    with pytest.raises(E0StratumError, match="stratum"):
        _ = validate_e0_package(manifest_path)


def test_e0_validator_rejects_tampered_hash(tmp_path: Path) -> None:
    # Given: a valid manifest followed by tampering
    manifest_path, records_path = write_e0_package(tmp_path)
    _ = records_path.write_text("tampered\n", encoding="utf-8")

    # When/Then: the declared content hash fails
    with pytest.raises(E0HashError, match="hash"):
        _ = validate_e0_package(manifest_path)
