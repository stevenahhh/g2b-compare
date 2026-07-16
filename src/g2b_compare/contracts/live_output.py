"""Deterministic publication for verified live contract evidence."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict

from g2b_compare.contracts.capture import (  # noqa: TC001
    CaptureBlockedError,
    OperationCapture,
)
from g2b_compare.contracts.manifest import ContractManifest  # noqa: TC001
from g2b_compare.contracts.quota import Operation  # noqa: TC001
from g2b_compare.contracts.redact import serialize_redacted
from g2b_compare.contracts.share import SharePreflightResult  # noqa: TC001

EVIDENCE_ROOT: Final = Path(".omo/evidence/task-2-contract")
BLOCKER_PATH: Final = EVIDENCE_ROOT / "live-blocker.json"


class LiveOperationRecord(BaseModel):
    """Redacted publication record for one verified operation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    operation: Operation
    transitions: tuple[str, ...]
    attempt_ledger_ids: tuple[int, ...]
    accepted_page_size: int
    observed_max_page_size: int
    source_payload_sha256: str
    manifest: ContractManifest
    preflight: SharePreflightResult


class LiveObservedDocument(BaseModel):
    """Canonical six-operation verified output document."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    manifests: tuple[LiveOperationRecord, ...]


class LiveBlockerRecord(BaseModel):
    """Canonical sanitized failure document."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    http_calls: int
    operation: str
    reason: str
    status: Literal["BLOCKED"] = "BLOCKED"
    status_code: int | None = None


def publish_success(
    root: Path,
    captures: tuple[OperationCapture, ...],
    secret: str,
) -> tuple[Path, ...]:
    """Stage a complete redacted bundle before replacing last-good files."""
    document = LiveObservedDocument(
        manifests=tuple(
            LiveOperationRecord(
                operation=item.operation,
                transitions=item.transitions,
                attempt_ledger_ids=item.attempt_ledger_ids,
                accepted_page_size=item.accepted_page_size,
                observed_max_page_size=item.observed_max_page_size,
                source_payload_sha256=item.source_payload_sha256,
                manifest=item.manifest,
                preflight=item.share_link_preflight,
            )
            for item in captures
        )
    )
    outputs = _success_outputs(captures, document)
    if any(secret.encode("utf-8") in content for content in outputs.values()):
        raise SecretPublicationError
    staging = root / f".capture-staging-{uuid.uuid4().hex}"
    try:
        for relative, content in outputs.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = target.write_bytes(content)
        for relative in sorted(outputs, key=lambda path: path.as_posix()):
            source = staging / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = source.replace(target)
        blocker = root / BLOCKER_PATH
        if blocker.exists():
            blocker.unlink()
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    ordered = sorted(outputs, key=lambda item: item.as_posix())
    return tuple(root / path for path in ordered)


class SecretPublicationError(RuntimeError):
    """A secret canary reached staged publication bytes."""


def publish_blocker(root: Path, failure: CaptureBlockedError) -> Path:
    """Atomically publish only sanitized failure facts."""
    receipt = LiveBlockerRecord(
        http_calls=failure.http_calls,
        operation=failure.operation,
        reason=failure.reason,
        status_code=failure.status_code,
    )
    target = root / BLOCKER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
    content = receipt.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
    _ = temporary.write_bytes(content)
    _ = temporary.replace(target)
    return target


def _success_outputs(
    captures: tuple[OperationCapture, ...],
    document: LiveObservedDocument,
) -> dict[Path, bytes]:
    json_bytes = document.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
    markdown = _markdown(captures)
    outputs = {
        Path("docs/api-contract-observed.json"): json_bytes,
        Path("docs/api-contract-observed.md"): markdown,
        EVIDENCE_ROOT / "manual-qa.json": serialize_redacted(
            {
                "http_calls": sum(len(item.attempt_ledger_ids) for item in captures),
                "operations_verified": len(captures),
                "status": "VERIFIED",
            }
        ),
        EVIDENCE_ROOT / "secret-scan.json": serialize_redacted(
            {"matches": 0, "status": "CLEAN"}
        ),
    }
    for item in captures:
        family = "attributes" if item.operation.value.endswith("List02") else "shopping"
        outputs[Path("tests/fixtures/api") / family / f"{item.operation}.json"] = (
            item.fixture
        )
    return outputs


def _markdown(captures: tuple[OperationCapture, ...]) -> bytes:
    lines = [
        "# G2B API contract observations",
        "",
        "| Operation | Phase | Attempts | Page sizes | Preflight |",
        "|---|---|---:|---:|---|",
    ]
    for item in captures:
        line = f"| `{item.operation}` | VERIFIED | {len(item.attempt_ledger_ids)} | "
        line += f"{item.accepted_page_size}/{item.observed_max_page_size} | "
        line += f"{item.share_link_preflight.outcome} |"
        lines.append(line)
    return ("\n".join(lines) + "\n").encode("utf-8")
