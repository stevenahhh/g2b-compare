"""Todo15 source and secret integrity boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from g2b_compare.evaluation.adjudication import (
    ExternalEvaluationBlockedError,
    require_external_evaluation,
)
from g2b_compare.evaluation.integrity import (
    IntegrityScanPlan,
    scan_integrity,
)

RUNTIME_SECRET = "todo15-runtime-" + "secret-0123456789abcdef"


def test_all_storage_integrity_detects_runtime_secret(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    leaked = runtime_root / "capture.log"
    _ = leaked.write_text(RUNTIME_SECRET, encoding="utf-8")
    plan = _plan(
        tmp_path,
        runtime_root=runtime_root,
        secret=RUNTIME_SECRET,
    )

    evidence = scan_integrity(plan)

    assert tuple(leak.path for leak in evidence.secret_leaks) == (leaked,)


def test_source_integrity_detects_mutation(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    plan = _plan(tmp_path, runtime_root=runtime_root)
    mutated = tmp_path / plan.source_paths[2]
    _ = mutated.write_bytes(b"mutated")

    evidence = scan_integrity(plan)

    assert not evidence.source_hashes_match
    assert evidence.source_count == 0


def test_external_evaluation_missing_manifest_is_blocked_not_generated(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ExternalEvaluationBlockedError,
        match="missing-gold-manifest",
    ):
        _ = require_external_evaluation(
            tmp_path / "gold-v1.manifest.json",
            tmp_path / "e0-package" / "manifest.json",
        )


def test_external_evaluation_never_accepts_a_fixture_claim_as_independence(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "gold-v1.manifest.json"
    _ = manifest.write_text('{"schema_version":"fixture"}\n', encoding="utf-8")
    source = tmp_path / "e0-package" / "manifest.json"
    source.parent.mkdir()
    _ = source.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        ExternalEvaluationBlockedError,
        match="invalid-external-evaluation",
    ):
        _ = require_external_evaluation(
            manifest,
            source,
        )


def _plan(
    root: Path,
    *,
    runtime_root: Path,
    secret: str | None = None,
) -> IntegrityScanPlan:
    source_paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    baseline = root / "source-artifacts.sha256"
    rows: list[str] = []
    for index, source_path in enumerate(source_paths):
        payload = f"source-{index}".encode()
        _ = (root / source_path).write_bytes(payload)
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {source_path.as_posix()}")
    _ = baseline.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return IntegrityScanPlan(
        repository_root=Path.cwd(),
        runtime_root=runtime_root,
        source_root=root,
        source_paths=source_paths,
        baseline_path=baseline.relative_to(root),
        secret=secret,
    )
