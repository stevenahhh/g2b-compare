"""Binding validation for the Tauri parity evidence manifest."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/tauri-parity-matrix.md"
MANIFEST = ROOT / "docs/tauri-parity-evidence-manifest.json"
ID = re.compile(r"^(?:SHELL|CAT|EST|DATA|OFF|DB|PKG)-\d{3}$")
ARTIFACTS = {".png", ".jpg", ".jpeg", ".webp", ".xlsx"}
ITEM_FIELDS = {
    "id",
    "requirement",
    "implementation_paths",
    "regression_tests",
    "final_gates",
    "evidence",
    "status",
    "blockers",
}


def test_tauri_parity_evidence_manifest_is_complete_and_binding() -> None:
    matrix = matrix_requirements()
    manifest = load(MANIFEST)
    validate_coverage(matrix, manifest)
    for item in manifest["items"]:
        validate_item(item, matrix)


def matrix_requirements() -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| (?:SHELL|CAT|EST|DATA|OFF|DB|PKG)-\d{3} \|", line):
            continue
        fields = [field.strip() for field in line.split("|")[1:-1]]
        assert fields[0] not in requirements
        requirements[fields[0]] = fields[1]
    assert len(requirements) == 70
    return requirements


def validate_coverage(matrix: dict[str, str], manifest: dict) -> None:
    assert manifest["schema_version"] == 1
    assert manifest["matrix_path"] == "docs/tauri-parity-matrix.md"
    items = manifest["items"]
    assert isinstance(items, list)
    assert len(items) == 70
    identifiers = [item["id"] for item in items]
    assert len(identifiers) == len(set(identifiers))
    assert set(identifiers) == set(matrix)
    assert all(ID.fullmatch(identifier) for identifier in identifiers)
    assert manifest["status_summary"] == {
        "passed": sum(item["status"] == "passed" for item in items),
        "blocked": sum(item["status"] == "blocked" for item in items),
    }


def validate_item(item: dict, matrix: dict[str, str]) -> None:
    assert set(item) == ITEM_FIELDS
    assert item["requirement"] == matrix[item["id"]]
    validate_sources(item["implementation_paths"])
    validate_regression_tests(item["regression_tests"])
    validate_final_gates(item["final_gates"])
    validate_evidence(item["evidence"])
    if item["status"] == "passed":
        assert item["blockers"] == []
        assert all_verified(item)
        return
    assert item["status"] == "blocked"
    assert item["blockers"]
    assert any_unverified(item)


def validate_sources(sources: list[str]) -> None:
    assert sources
    for source in sources:
        assert source.startswith("desktop/")
        assert repository_path(source).suffix.lower() != ".md"


def validate_regression_tests(section: dict) -> None:
    assert section["status"] in {"verified", "missing", "failed"}
    if section["status"] == "missing":
        assert section["tests"] == []
        assert section["reason"]
        return
    assert section["tests"]
    if section["status"] == "failed":
        assert section["reason"]
    for test in section["tests"]:
        test_path = repository_path(test["path"])
        assert test_path.suffix in {".js", ".ts", ".rs", ".py"}
        assert test["name"] in test_path.read_text(encoding="utf-8")


def validate_final_gates(section: dict) -> None:
    assert section["status"] in {"verified", "missing"}
    if section["status"] == "missing":
        assert section["gates"] == []
        assert section["reason"]
        return
    assert section["gates"]
    for gate in section["gates"]:
        assert gate["name"]
        assert gate["command"]
        receipt_events(load(repository_path(gate["receipt_path"])), gate["checks"])


def validate_evidence(section: dict) -> None:
    assert section["status"] in {"verified", "missing"}
    if section["status"] == "missing":
        assert set(section) == {"status", "reason"}
        assert section["reason"]
        return
    receipt_path = repository_path(section["receipt_path"])
    assert receipt_path.suffix == ".json"
    assert digest(receipt_path) == section["receipt_sha256"]
    events = receipt_events(load(receipt_path), section["checks"])
    artifact_paths = section["artifact_paths"]
    assert set(artifact_paths) == set(section["artifact_sha256"])
    receipt_values = {value for event in events for value in strings(event["details"])}
    for artifact in artifact_paths:
        validate_artifact(section, receipt_path, receipt_values, artifact)


def validate_artifact(
    section: dict,
    receipt_path: Path,
    receipt_values: set[str],
    artifact: str,
) -> None:
    artifact_path = repository_path(artifact)
    assert artifact_path.suffix.lower() in ARTIFACTS
    assert digest(artifact_path) == section["artifact_sha256"][artifact]
    assert any(
        (receipt_path.parent / value).resolve() == artifact_path.resolve()
        for value in receipt_values
    )


def receipt_events(receipt: dict, checks: list[dict]) -> list[dict]:
    assert receipt["outcome"] == "passed"
    assert checks
    selected = []
    for check in checks:
        matches = [
            event for event in receipt["events"] if event["check"] == check["name"]
        ]
        assert len(matches) == 1
        event = matches[0]
        assert event["status"] == "passed"
        details = event["details"]
        assert not any(is_invalid_evidence_text(text) for text in strings(details))
        assert_assertions(details, check["assertions"])
        selected.append(event)
    cleanup = next(event for event in selected if event["check"] == "cleanup")
    assert cleanup["details"]["removed"] is True
    assert cleanup["details"]["path_exists_after_cleanup"] is False
    return selected


def assert_assertions(details: dict, assertions: dict) -> None:
    for dotted, expected in assertions.items():
        assert not is_invalid_evidence_text(expected)
        current = details
        for part in dotted.split("."):
            current = current[part]
        assert current == expected


def all_verified(item: dict) -> bool:
    return all(
        item[key]["status"] == "verified"
        for key in ("regression_tests", "final_gates", "evidence")
    )


def any_unverified(item: dict) -> bool:
    return any(
        item[key]["status"] != "verified"
        for key in ("regression_tests", "final_gates", "evidence")
    )


def is_invalid_evidence_text(value: object) -> bool:
    return isinstance(value, str) and (
        "unavailable" in value.lower() or "error-boundary" in value.lower()
    )


def repository_path(value: str) -> Path:
    assert value
    assert not value.startswith(("/", "./"))
    assert "\\" not in value
    assert ":" not in value
    assert ".." not in Path(value).parts
    result = ROOT / value
    assert result.is_file(), value
    return result


def strings(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(strings(child) for child in value))
    return set()


def digest(file_path: Path) -> str:
    hasher = sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load(file_path: Path) -> dict:
    result = json.loads(file_path.read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result
