"""Runtime quota reservation lifecycle with request-context logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from g2b_compare.db.models import QuotaReservationInput
from g2b_compare.observability.logging import configure_logging, operation_log

if TYPE_CHECKING:
    from g2b_compare.contracts.quota import Operation
    from g2b_compare.db.ingest import IngestRepository

KST_OFFSET: Final = timedelta(hours=9)
HTTP_OK: Final = 200


@dataclass(frozen=True, slots=True)
class RuntimeQuotaGate:
    """Persist one ledger row and one contextual log for every runtime attempt."""

    repository: IngestRepository
    quotas: dict[Operation, int]

    def reserve(self, operation: Operation) -> int:
        """Atomically reserve one provider call under its operation ceiling."""
        now = datetime.now(UTC)
        reservation = self.repository.reserve_quota(
            QuotaReservationInput(
                operation.value,
                now.isoformat(),
                (now - timedelta(hours=24)).isoformat(),
                (now + KST_OFFSET).date().isoformat(),
                self.quotas[operation],
            )
        )
        operation_log(
            configure_logging(),
            operation=operation.value,
            status="quota-reserved",
            context={"run": reservation},
        )
        return reservation

    def finish(
        self,
        reservation_id: int,
        status_code: int,
        operation: Operation,
        window: int,
        page: int,
    ) -> None:
        """Finalize one non-refundable attempt with real request context."""
        self.repository.finish_quota(
            reservation_id,
            status_code,
            success=status_code == HTTP_OK,
        )
        operation_log(
            configure_logging(),
            operation=operation.value,
            status=(
                "succeeded" if status_code == HTTP_OK else f"failed-http-{status_code}"
            ),
            context={"run": reservation_id, "window": window, "page": page},
        )
