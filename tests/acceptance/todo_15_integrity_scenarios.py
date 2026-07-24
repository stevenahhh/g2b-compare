"""Drive Todo15 integrity contracts through real persisted storage."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

from g2b_compare.evaluation.contracts import (
    Todo15ContractError,
    validate_integrity_contract,
)
from g2b_compare.evaluation.integrity import IntegrityScanPlan, scan_integrity
from g2b_compare.paths import SOURCE_ARTIFACTS, SOURCE_HASH_BASELINE

WORKSPACE_ROOT = Path(__file__).parents[2]


def validate_integrity_happy() -> None:
    """Verify the actual runtime storage and immutable source artifacts."""
    evidence = scan_integrity(
        IntegrityScanPlan(
            repository_root=WORKSPACE_ROOT,
            runtime_root=WORKSPACE_ROOT / "var",
            source_root=WORKSPACE_ROOT,
            source_paths=SOURCE_ARTIFACTS,
            baseline_path=SOURCE_HASH_BASELINE,
            secret=os.getenv("G2B_SERVICE_KEY"),
        )
    )
    validate_integrity_contract(evidence.facts)
    if evidence.source_count != 4:
        reason = "source-mutation"
        raise Todo15ContractError(reason)


def run_integrity_failure(
    scenario: Literal["secret-runtime", "source-mutation"],
    temp_root: Path,
) -> None:
    """Mutate runtime storage or a source receipt and require typed rejection."""
    runtime_root = temp_root / "runtime"
    runtime_root.mkdir()
    source_root, source_paths, baseline_path = _source_fixture(temp_root)
    secret: str | None = None
    if scenario == "secret-runtime":
        secret = "todo15-runtime-" + "secret-0123456789abcdef"
        _ = (runtime_root / "capture.log").write_text(secret, encoding="utf-8")
    else:
        _ = (source_root / source_paths[2]).write_bytes(b"mutated")
    evidence = scan_integrity(
        IntegrityScanPlan(
            repository_root=WORKSPACE_ROOT,
            runtime_root=runtime_root,
            source_root=source_root,
            source_paths=source_paths,
            baseline_path=baseline_path,
            secret=secret,
        )
    )
    validate_integrity_contract(evidence.facts)


def _source_fixture(root: Path) -> tuple[Path, tuple[Path, ...], Path]:
    source_root = root / "source"
    source_root.mkdir()
    source_paths = tuple(Path(f"source-{index}.bin") for index in range(4))
    rows: list[str] = []
    for index, source_path in enumerate(source_paths):
        payload = f"source-{index}".encode()
        _ = (source_root / source_path).write_bytes(payload)
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {source_path.as_posix()}")
    baseline_path = Path("source-artifacts.sha256")
    _ = (source_root / baseline_path).write_text(
        "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return source_root, source_paths, baseline_path
