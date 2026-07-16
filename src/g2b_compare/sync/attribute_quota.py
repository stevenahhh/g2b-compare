"""Persistent quota authorization for attribute HTTP attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final, Protocol, final, override

from g2b_compare.contracts.manifest import ContractManifest, VerifiedState
from g2b_compare.contracts.quota import Operation, effective_ceiling
from g2b_compare.db.models import QuotaReservationInput
from g2b_compare.db.repository import RepositoryContractError

if TYPE_CHECKING:
    from g2b_compare.db.ingest import IngestRepository

_ATTRIBUTE_OPERATION: Final = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
_KST: Final = timezone(timedelta(hours=9))
_MIN_SAFE_DISPATCH: Final = 3
_HTTP_OK: Final = 200
_QUOTA_UNVERIFIED: Final = "quota-unverified"
_PROVIDER_WINDOW_INVALID: Final = "provider-window-invalid"
_PROBE_BUDGET_LOW: Final = "probe-budget-below-three"
_QUOTA_CEILING: Final = "quota-ceiling"


class QuotaWindowClock(Protocol):
    """Provide an aware current instant and observed provider-window start."""

    def now(self) -> datetime:
        """Return the current aware UTC-compatible instant."""
        ...

    def provider_window_start(self, now: datetime) -> datetime:
        """Return the observed provider window containing ``now``."""
        ...


@final
class AttributeQuotaError(Exception):
    """Sanitized denial before an attribute HTTP dispatch."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one public quota reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class AttributeReservation:
    """One persisted attempt authorized for immediate dispatch."""

    reservation_id: int
    attempted_at: datetime


@dataclass(frozen=True, slots=True)
class AttributeQuotaGate:
    """Atomically enforce verified rolling and provider quota windows."""

    repository: IngestRepository
    manifest: ContractManifest
    clock: QuotaWindowClock

    def __post_init__(self) -> None:
        """Reject any gate not bound to the verified attribute contract."""
        if self.manifest.operation is not _ATTRIBUTE_OPERATION or not isinstance(
            self.manifest.state, VerifiedState
        ):
            raise AttributeQuotaError(_QUOTA_UNVERIFIED)

    def reserve(self) -> AttributeReservation:
        """Persist one reservation immediately before its HTTP dispatch."""
        now = self.clock.now()
        provider_start = self.clock.provider_window_start(now)
        if provider_start > now:
            raise AttributeQuotaError(_PROVIDER_WINDOW_INVALID)
        ceiling = effective_ceiling(self.manifest.quota)
        if ceiling < _MIN_SAFE_DISPATCH:
            raise AttributeQuotaError(_PROBE_BUDGET_LOW)
        rolling_start = now - timedelta(hours=24) + timedelta(microseconds=1)
        conservative_start = min(rolling_start, provider_start)
        try:
            reservation_id = self.repository.reserve_quota(
                QuotaReservationInput(
                    operation=self.manifest.operation,
                    attempted_at_utc=now.isoformat(),
                    cutoff_utc=conservative_start.isoformat(),
                    kst_date=now.astimezone(_KST).date().isoformat(),
                    ceiling=ceiling,
                )
            )
        except RepositoryContractError:
            raise AttributeQuotaError(_QUOTA_CEILING) from None
        return AttributeReservation(reservation_id, now)

    def finish(self, reservation: AttributeReservation, status_code: int) -> None:
        """Finalize a reservation without refunding failed attempts."""
        self.repository.finish_quota(
            reservation.reservation_id,
            status_code,
            success=status_code == _HTTP_OK,
        )
