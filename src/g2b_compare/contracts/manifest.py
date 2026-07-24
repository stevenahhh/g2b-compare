"""Typed contract-probe manifest states."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from g2b_compare.contracts.quota import Operation, QuotaRow  # noqa: TC001

MAX_ATTEMPTS: Final = 5
MIN_VERIFIED_ATTEMPTS: Final = 3
ATTEMPT_ID_ERROR_CODE: Final = "attempt_ledger_id"
ATTEMPT_ID_ERROR_MESSAGE: Final = "attempt ledger IDs must be positive"
ATTEMPT_DUPLICATE_ERROR_CODE: Final = "attempt_ledger_duplicate"
ATTEMPT_DUPLICATE_ERROR_MESSAGE: Final = "attempt ledger IDs must be unique"
ATTEMPT_BUDGET_ERROR_CODE: Final = "attempt_budget"
ATTEMPT_BUDGET_ERROR_MESSAGE: Final = (
    "attempt ledger IDs exceed the five-call probe budget"
)
CONTRACT_FIELDS_ERROR_CODE: Final = "contract_fields"
CONTRACT_FIELDS_ERROR_MESSAGE: Final = (
    "contract field sets must be non-empty and unique"
)
VERIFICATION_ERROR_CODE: Final = "verification_attempts"
VERIFICATION_ERROR_MESSAGE: Final = (
    "VERIFIED state requires at least three attempt ledger IDs"
)
QUOTA_OPERATION_ERROR_CODE: Final = "quota_operation_mismatch"
QUOTA_OPERATION_ERROR_MESSAGE: Final = (
    "quota operation must match contract manifest operation"
)


class ProbePhase(StrEnum):
    """Exhaustive contract-probe phases."""

    DISCOVER = "DISCOVER"
    VERIFY_SCHEMA = "VERIFY_SCHEMA"
    VERIFY_LIMIT = "VERIFY_LIMIT"
    VERIFIED = "VERIFIED"


class ProbeStateBase(BaseModel):
    """Shared immutable attempt-ledger boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    attempt_ledger_ids: tuple[int, ...]

    @field_validator("attempt_ledger_ids")
    @classmethod
    def require_unique_attempts(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Reject reused, invalid, or over-budget HTTP attempt identities."""
        if any(attempt_id <= 0 for attempt_id in value):
            raise PydanticCustomError(
                ATTEMPT_ID_ERROR_CODE,
                ATTEMPT_ID_ERROR_MESSAGE,
            )
        if len(value) != len(set(value)):
            raise PydanticCustomError(
                ATTEMPT_DUPLICATE_ERROR_CODE,
                ATTEMPT_DUPLICATE_ERROR_MESSAGE,
            )
        if len(value) > MAX_ATTEMPTS:
            raise PydanticCustomError(
                ATTEMPT_BUDGET_ERROR_CODE,
                ATTEMPT_BUDGET_ERROR_MESSAGE,
            )
        return value


class DiscoverState(ProbeStateBase):
    """DISCOVER state before a stable non-empty candidate is selected."""

    phase: Literal[ProbePhase.DISCOVER] = ProbePhase.DISCOVER


class ObservedSchemaState(ProbeStateBase):
    """Shared evidence after a stable schema has been observed."""

    selected_candidate: str = Field(min_length=1)
    required_fields: tuple[str, ...]
    stable_key_fields: tuple[str, ...]

    @field_validator("required_fields", "stable_key_fields")
    @classmethod
    def canonical_nonempty_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Canonicalize a proven non-empty field set."""
        if not value or len(value) != len(set(value)):
            raise PydanticCustomError(
                CONTRACT_FIELDS_ERROR_CODE,
                CONTRACT_FIELDS_ERROR_MESSAGE,
            )
        return tuple(sorted(value))


class VerifySchemaState(ObservedSchemaState):
    """VERIFY_SCHEMA state with identity and page-size evidence."""

    phase: Literal[ProbePhase.VERIFY_SCHEMA] = ProbePhase.VERIFY_SCHEMA
    accepted_page_size: Literal[100] = 100


class VerifyLimitState(ObservedSchemaState):
    """VERIFY_LIMIT state with an accepted maximum page candidate."""

    phase: Literal[ProbePhase.VERIFY_LIMIT] = ProbePhase.VERIFY_LIMIT
    accepted_page_size: int = Field(ge=1, le=1000)
    observed_max_page_size: int = Field(ge=1, le=1000)


class VerifiedState(ObservedSchemaState):
    """Strict live-observed contract ready for downstream ingestion."""

    phase: Literal[ProbePhase.VERIFIED] = ProbePhase.VERIFIED
    accepted_page_size: int = Field(ge=1, le=1000)
    observed_max_page_size: int = Field(ge=1, le=1000)
    schema_fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_at: AwareDatetime
    provenance: Literal["live_observed"]
    quota_scope: Literal["operation"]
    quota_reset_source: Literal["unknown"]

    @model_validator(mode="after")
    def require_complete_attempt_sequence(self) -> Self:
        """Require the indivisible DISCOVER and two VERIFY attempts."""
        if len(self.attempt_ledger_ids) < MIN_VERIFIED_ATTEMPTS:
            raise PydanticCustomError(
                VERIFICATION_ERROR_CODE,
                VERIFICATION_ERROR_MESSAGE,
            )
        return self


type ProbeState = Annotated[
    DiscoverState | VerifySchemaState | VerifyLimitState | VerifiedState,
    Field(discriminator="phase"),
]


class ContractManifest(BaseModel):
    """One operation's quota authorization and typed probe state."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    operation: Operation
    quota: QuotaRow
    state: ProbeState

    @model_validator(mode="after")
    def require_matching_quota(self) -> Self:
        """Prevent authorization evidence from crossing operation identities."""
        if self.operation != self.quota.operation:
            raise PydanticCustomError(
                QUOTA_OPERATION_ERROR_CODE,
                QUOTA_OPERATION_ERROR_MESSAGE,
            )
        return self


def serialize_manifest(manifest: ContractManifest) -> bytes:
    """Serialize a typed manifest to stable UTF-8 JSON with one final LF."""
    return manifest.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
