"""Approved-operation quota contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Literal, Self, override

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

SHOPPING_SERVICE_ID: Final = "15129471"
ATTRIBUTE_SERVICE_ID: Final = "15129417"
MIN_PROBE_ATTEMPTS: Final = 3
MAX_PROBE_ATTEMPTS: Final = 5
SERVICE_ERROR_CODE: Final = "service_operation_mismatch"
SERVICE_ERROR_MESSAGE: Final = "operation is not authorized by the declared service"
OPERATION_SET_ERROR_CODE: Final = "approved_operation_set"
OPERATION_SET_ERROR_MESSAGE: Final = (
    "quota manifest must contain the six approved operations exactly once"
)


class Operation(StrEnum):
    """The six independently authorized G2B operations."""

    GET_MAS_CONTRACT_PRODUCT_INFO = "getMASCntrctPrdctInfoList"
    GET_UNIT_CONTRACT_PRODUCT_INFO = "getUcntrctPrdctInfoList"
    GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO = "getThptyUcntrctPrdctInfoList"
    GET_SHOPPING_MALL_PRODUCT_INFO = "getShoppingMallPrdctInfoList"
    GET_DELIVERY_REQUEST_DETAIL = "getDlvrReqDtlInfoList"
    GET_PRODUCT_INDIVIDUAL_ATTRIBUTE = "getPrdctIndvAtrbInfoList02"


_SERVICE_IDS: Final = MappingProxyType(
    {
        Operation.GET_MAS_CONTRACT_PRODUCT_INFO: SHOPPING_SERVICE_ID,
        Operation.GET_UNIT_CONTRACT_PRODUCT_INFO: SHOPPING_SERVICE_ID,
        Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO: SHOPPING_SERVICE_ID,
        Operation.GET_SHOPPING_MALL_PRODUCT_INFO: SHOPPING_SERVICE_ID,
        Operation.GET_DELIVERY_REQUEST_DETAIL: SHOPPING_SERVICE_ID,
        Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE: ATTRIBUTE_SERVICE_ID,
    }
)


def service_id_for(operation: Operation) -> str:
    """Return the approved service identifier owning an operation."""
    return _SERVICE_IDS[operation]


class QuotaRow(BaseModel):
    """A sanitized approved-operation row parsed from account evidence."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    service_id: str = Field(min_length=1)
    operation: Operation
    approved: Literal[True]
    daily_quota: int = Field(gt=0)
    reset_timezone: Literal["unknown"]
    reset_window: Literal["unknown"]
    observed_at: AwareDatetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_expected_service(self) -> Self:
        """Bind each operation to its separately approved service."""
        expected = service_id_for(self.operation)
        if self.service_id != expected:
            raise PydanticCustomError(
                SERVICE_ERROR_CODE,
                SERVICE_ERROR_MESSAGE,
            )
        return self


class QuotaManifest(BaseModel):
    """Canonical six-row authorization and quota observation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[QuotaRow, ...]

    @field_validator("rows")
    @classmethod
    def require_exact_operation_set(
        cls,
        value: tuple[QuotaRow, ...],
    ) -> tuple[QuotaRow, ...]:
        """Require each approved operation exactly once."""
        operations = tuple(row.operation for row in value)
        if len(operations) != len(Operation) or set(operations) != set(Operation):
            raise PydanticCustomError(
                OPERATION_SET_ERROR_CODE,
                OPERATION_SET_ERROR_MESSAGE,
            )
        operation_order = tuple(Operation)
        return tuple(
            sorted(value, key=lambda row: operation_order.index(row.operation))
        )


class QuotaUsage(BaseModel):
    """Observed rolling-window consumption for one operation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    operation: Operation
    consumed_attempts: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class ProbeBudget:
    """Derived bounded HTTP allowance for contract verification."""

    ceiling: int
    consumed_attempts: int
    remaining_attempts: int
    allowed_http_attempts: int


@dataclass(frozen=True, slots=True)
class QuotaOperationMismatchError(Exception):
    """Quota authorization and rolling usage refer to different operations."""

    quota_operation: Operation
    usage_operation: Operation

    @override
    def __str__(self) -> str:
        return (
            "quota operation does not match usage operation: "
            f"{self.quota_operation} != {self.usage_operation}"
        )


def effective_ceiling(row: QuotaRow) -> int:
    """Reserve the larger of ten percent or one hundred calls."""
    ten_percent = (row.daily_quota + 9) // 10
    return max(0, row.daily_quota - max(ten_percent, 100))


def probe_budget(row: QuotaRow, usage: QuotaUsage) -> ProbeBudget:
    """Allow a probe only when DISCOVER and both VERIFY calls fit."""
    if row.operation != usage.operation:
        raise QuotaOperationMismatchError(
            quota_operation=row.operation,
            usage_operation=usage.operation,
        )
    ceiling = effective_ceiling(row)
    remaining = max(0, ceiling - usage.consumed_attempts)
    allowed = (
        min(MAX_PROBE_ATTEMPTS, remaining) if remaining >= MIN_PROBE_ATTEMPTS else 0
    )
    return ProbeBudget(
        ceiling=ceiling,
        consumed_attempts=usage.consumed_attempts,
        remaining_attempts=remaining,
        allowed_http_attempts=allowed,
    )
