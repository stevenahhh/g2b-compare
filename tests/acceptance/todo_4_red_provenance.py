"""Audit the immutable, explicitly synthetic Todo 4 RED receipt."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_PROVENANCE_SHA256: Final = (
    "e996e1231c36a85f7e4da901ffae2d49fdd8da619bcdbb089a641a93db9ca67c"
)
EXPECTED_SOURCE_JUNIT_SHA256: Final = (
    "17487aaac895fdd3c61e3cc499baa18b8043900deb54a06b6300e5f6e02c4e74"
)
EXPECTED_SIGNATURES: Final = 17
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
GIT_SHA1_PATTERN: Final = r"^[0-9a-f]{40}$"


class RegistryContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message_regex: str


class RedSignature(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    scenario_id: str
    node_id: str
    assertion_class: str
    message_regex: str
    failure_message_sha256: str = Field(pattern=SHA256_PATTERN)


class RedProvenance(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    schema_version: Literal["todo-4-red-provenance-v1"]
    capture_method: Literal["synthetic-post-success"]
    evidence_status: Literal["synthetic-non-failing-first"]
    implementation_commit: str = Field(pattern=GIT_SHA1_PATTERN)
    legacy_environment_variable: str
    limitation: str = Field(min_length=1)
    source_command: str
    source_junit_sha256: str = Field(pattern=SHA256_PATTERN)
    signatures: tuple[RedSignature, ...]


class RedProvenanceReason(StrEnum):
    FIXTURE_HASH = "immutable fixture hash changed"
    JUNIT_HASH = "source JUnit hash changed"
    SIGNATURE_COUNT = "signature count or uniqueness changed"
    REGISTRY_SCENARIOS = "registry scenario mapping changed"
    NODE_IDS = "node IDs are not unique"
    REGISTRY_SIGNATURE = "registry signature changed"


class RedProvenanceError(RuntimeError):
    reason: RedProvenanceReason
    scenario_id: str

    def __init__(
        self,
        reason: RedProvenanceReason,
        scenario_id: str = "",
    ) -> None:
        super().__init__(reason, scenario_id)
        self.reason = reason
        self.scenario_id = scenario_id

    @override
    def __str__(self) -> str:
        suffix = f": {self.scenario_id}" if self.scenario_id else ""
        return f"Todo 4 RED provenance mismatch: {self.reason}{suffix}"


def audit_red_provenance(
    provenance_path: Path,
    registry_path: Path,
) -> RedProvenance:
    """Require immutable historical signatures to map one-to-one to registry."""
    provenance_bytes = provenance_path.read_bytes()
    if hashlib.sha256(provenance_bytes).hexdigest() != EXPECTED_PROVENANCE_SHA256:
        raise RedProvenanceError(RedProvenanceReason.FIXTURE_HASH)
    provenance = RedProvenance.model_validate_json(provenance_bytes)
    if provenance.source_junit_sha256 != EXPECTED_SOURCE_JUNIT_SHA256:
        raise RedProvenanceError(RedProvenanceReason.JUNIT_HASH)

    registry = TypeAdapter(dict[str, RegistryContract]).validate_json(
        registry_path.read_bytes()
    )
    todo_registry = {
        scenario_id: contract
        for scenario_id, contract in registry.items()
        if scenario_id.startswith("todo-4/")
    }
    signatures = {
        signature.scenario_id: signature for signature in provenance.signatures
    }
    if (
        len(provenance.signatures) != EXPECTED_SIGNATURES
        or len(signatures) != EXPECTED_SIGNATURES
    ):
        raise RedProvenanceError(RedProvenanceReason.SIGNATURE_COUNT)
    if signatures.keys() != todo_registry.keys():
        raise RedProvenanceError(RedProvenanceReason.REGISTRY_SCENARIOS)
    node_ids = {signature.node_id for signature in provenance.signatures}
    if len(node_ids) != EXPECTED_SIGNATURES:
        raise RedProvenanceError(RedProvenanceReason.NODE_IDS)
    for scenario_id, signature in signatures.items():
        contract = todo_registry[scenario_id]
        if (
            signature.assertion_class != contract.assertion_class
            or signature.message_regex != contract.message_regex
        ):
            raise RedProvenanceError(
                RedProvenanceReason.REGISTRY_SIGNATURE,
                scenario_id,
            )
    return provenance
