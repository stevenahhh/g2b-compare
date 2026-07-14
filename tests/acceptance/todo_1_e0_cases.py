from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, ClassVar, Literal, assert_never

from pydantic import BaseModel, ConfigDict

from g2b_compare.evaluation.e0_schema import validate_e0_package

if TYPE_CHECKING:
    from pathlib import Path

type E0Scenario = Literal[
    "e0-missing-file",
    "e0-schema",
    "e0-count",
    "e0-stratum",
    "e0-hash",
]


class ManifestFileSpec(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str
    sha256: str
    record_count: int
    strata: dict[str, int]


class ManifestSpec(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str
    total_count: int
    strata: dict[str, int]
    files: tuple[ManifestFileSpec, ...]


class ErrorManifestSpec(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: str
    total_count: int
    stratum: str
    file_hash: str


def validate_happy_e0(temp_root: Path) -> int:
    records_hash = _write_records(temp_root, "positive")
    _write_manifest(
        temp_root,
        ManifestSpec(
            schema_version="e0-v1",
            total_count=1,
            strata={"positive": 1},
            files=(
                ManifestFileSpec(
                    path="records.jsonl",
                    sha256=records_hash,
                    record_count=1,
                    strata={"positive": 1},
                ),
            ),
        ),
    )
    return validate_e0_package(temp_root / "manifest.json").total_count


def run_e0_scenario(scenario: E0Scenario, temp_root: Path) -> None:
    match scenario:
        case "e0-missing-file":
            _write_error_manifest(
                temp_root,
                ErrorManifestSpec(
                    schema_version="e0-v1",
                    total_count=1,
                    stratum="positive",
                    file_hash="0" * 64,
                ),
            )
            _ = validate_e0_package(temp_root / "manifest.json")
        case "e0-schema":
            _write_error_manifest(
                temp_root,
                ErrorManifestSpec(
                    schema_version="e0-v0",
                    total_count=1,
                    stratum="positive",
                    file_hash="0" * 64,
                ),
            )
            _ = validate_e0_package(temp_root / "manifest.json")
        case "e0-count":
            records_hash = _write_records(temp_root, "positive")
            _write_error_manifest(
                temp_root,
                ErrorManifestSpec(
                    schema_version="e0-v1",
                    total_count=2,
                    stratum="positive",
                    file_hash=records_hash,
                ),
            )
            _ = validate_e0_package(temp_root / "manifest.json")
        case "e0-stratum":
            records_hash = _write_records(temp_root, "negative")
            _write_error_manifest(
                temp_root,
                ErrorManifestSpec(
                    schema_version="e0-v1",
                    total_count=1,
                    stratum="positive",
                    file_hash=records_hash,
                ),
            )
            _ = validate_e0_package(temp_root / "manifest.json")
        case "e0-hash":
            _ = _write_records(temp_root, "positive")
            _write_error_manifest(
                temp_root,
                ErrorManifestSpec(
                    schema_version="e0-v1",
                    total_count=1,
                    stratum="positive",
                    file_hash="0" * 64,
                ),
            )
            _ = validate_e0_package(temp_root / "manifest.json")
        case _:
            assert_never(scenario)


def _write_records(root: Path, stratum: str) -> str:
    payload = f'{{"record_id":"r1","stratum":"{stratum}","label":1}}\n'.encode()
    _ = (root / "records.jsonl").write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_error_manifest(root: Path, spec: ErrorManifestSpec) -> None:
    _write_manifest(
        root,
        ManifestSpec(
            schema_version=spec.schema_version,
            total_count=spec.total_count,
            strata={spec.stratum: 1},
            files=(
                ManifestFileSpec(
                    path="records.jsonl",
                    sha256=spec.file_hash,
                    record_count=1,
                    strata={spec.stratum: 1},
                ),
            ),
        ),
    )


def _write_manifest(root: Path, manifest: ManifestSpec) -> None:
    _ = (root / "manifest.json").write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )
