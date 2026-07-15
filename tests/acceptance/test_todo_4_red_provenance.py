from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.acceptance.todo_4_red_provenance import (
    RedProvenance,
    RedProvenanceError,
    audit_red_provenance,
)

ACCEPTANCE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ACCEPTANCE_ROOT.parents[1]
PROVENANCE = ACCEPTANCE_ROOT / "provenance" / "todo-4-red-v1.json"
REGISTRY = ACCEPTANCE_ROOT / "expected-failures.json"
RUNTIME_ACCEPTANCE = ACCEPTANCE_ROOT / "test_todo_4.py"


@pytest.fixture(scope="session")
def audited_red_provenance() -> RedProvenance:
    return audit_red_provenance(PROVENANCE, REGISTRY)


def test_historical_red_provenance_is_immutable_and_honest(
    audited_red_provenance: RedProvenance,
) -> None:
    assert audited_red_provenance.evidence_status == "synthetic-non-failing-first"
    assert audited_red_provenance.capture_method == "synthetic-post-success"
    assert len(audited_red_provenance.signatures) == 17


def test_historical_red_provenance_rejects_tamper(tmp_path: Path) -> None:
    original = PROVENANCE.read_text(encoding="utf-8")
    tampered = original.replace("TokenOrderError", "TamperedError", 1)
    assert tampered != original
    tampered_path = tmp_path / PROVENANCE.name
    _ = tampered_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(RedProvenanceError, match="immutable fixture hash changed"):
        _ = audit_red_provenance(tampered_path, REGISTRY)


def test_runtime_acceptance_ignores_legacy_red_environment(
    audited_red_provenance: RedProvenance,
) -> None:
    environment = os.environ.copy()
    environment[audited_red_provenance.legacy_environment_variable] = "1"
    result = subprocess.run(  # noqa: S603 - fixed local pytest command.
        [
            sys.executable,
            "-m",
            "pytest",
            str(RUNTIME_ACCEPTANCE),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "17 passed" in result.stdout


def test_runtime_acceptance_does_not_import_red_provenance() -> None:
    source = RUNTIME_ACCEPTANCE.read_text(encoding="utf-8")

    assert "todo_4_red_provenance" not in source
