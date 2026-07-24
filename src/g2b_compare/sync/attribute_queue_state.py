"""Pure attribute queue planning and quota state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal, final, override

from g2b_compare.contracts.manifest import ContractManifest, VerifiedState
from g2b_compare.contracts.quota import Operation, effective_ceiling

if TYPE_CHECKING:
    from g2b_compare.db.models import AttributeRecordInput

ATTRIBUTE_OPERATION: Final = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
ATTRIBUTE_TTL: Final = timedelta(days=90)
MIN_SAFE_DISPATCH: Final = 3
QUOTA_UNVERIFIED: Final = "quota-unverified"
INVALID_QUOTA_USAGE: Final = "quota-usage-invalid"
ATTRIBUTE_ORIGIN_MISSING: Final = "attribute-origin-missing"
type QueueReason = Literal["new", "changed", "ttl", "never-complete"]
type ApplyResult = Literal["applied", "retained", "raw-only"]


@final
class AttributeQueueError(ValueError):
    """Sanitized queue-policy failure."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one caller-visible policy reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class CatalogAttributeInput:
    """Catalog product facts relevant to attribute refresh."""

    product_id: str
    category_priority: int
    source_fingerprint_sha: str


@dataclass(frozen=True, slots=True)
class PreviousAttribute:
    """Prior complete-state facts used for carry-forward."""

    product_id: str
    source_fingerprint_sha: str
    completed_at: datetime
    complete: bool
    origin_snapshot_id: int


@dataclass(frozen=True, slots=True)
class QueuePlanningInput:
    """One deterministic generation planning boundary."""

    catalog_generation_id: int
    products: tuple[CatalogAttributeInput, ...]
    previous: tuple[PreviousAttribute, ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """One product selected for attribute refresh."""

    catalog_generation_id: int
    product_id: str
    category_priority: int
    source_fingerprint_sha: str
    reason: QueueReason


@dataclass(frozen=True, slots=True)
class DispatchBudget:
    """Conservative allowance across rolling provider windows."""

    ceiling: int
    consumed_calls: int
    allowed_calls: int


@dataclass(frozen=True, slots=True)
class CarryForwardEntry:
    """One unchanged complete product and its exact origin snapshot."""

    product_id: str
    source_fingerprint_sha: str
    origin_snapshot_id: int


@dataclass(frozen=True, slots=True)
class AttributePlan:
    """Queued and carried-forward decisions for one generation."""

    queued: tuple[QueueEntry, ...]
    carried: tuple[CarryForwardEntry, ...]

    @property
    def carried_forward(self) -> tuple[str, ...]:
        """Return the stable product-only compatibility projection."""
        return tuple(item.product_id for item in self.carried)

    def dispatchable(self, budget: DispatchBudget) -> tuple[QueueEntry, ...]:
        """Return the deterministic prefix allowed by current quota."""
        return self.queued[: budget.allowed_calls]


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    """Verified authorization plus both observed usage windows."""

    manifest: ContractManifest
    rolling_consumed: int
    provider_window_consumed: int


@dataclass(frozen=True, slots=True)
class CompleteFetch:
    """Fully staged page set eligible for atomic replacement."""

    records: tuple[AttributeRecordInput, ...]
    completed_at: str
    official_no_data: bool = False


@dataclass(frozen=True, slots=True)
class FailedFetch:
    """Incomplete fetch that must retain prior rows and retry."""

    reason: str


type FetchOutcome = CompleteFetch | FailedFetch


@dataclass(frozen=True, slots=True)
class FetchCommit:
    """Generation-pinned attribute publication request."""

    expected_generation_id: int
    current_generation_id: int
    snapshot_id: int
    product_id: str
    source_fingerprint_sha: str
    outcome: FetchOutcome
    origin_snapshot_id: int | None = None


def dispatch_budget(window: QuotaWindow) -> DispatchBudget:
    """Apply the observed ceiling and indivisible three-call minimum."""
    _require_verified(window.manifest)
    if window.rolling_consumed < 0 or window.provider_window_consumed < 0:
        raise AttributeQueueError(INVALID_QUOTA_USAGE)
    ceiling = effective_ceiling(window.manifest.quota)
    consumed = max(window.rolling_consumed, window.provider_window_consumed)
    remaining = max(0, ceiling - consumed)
    allowed = remaining if remaining >= MIN_SAFE_DISPATCH else 0
    return DispatchBudget(ceiling, consumed, allowed)


def plan_attribute_queue(planning: QueuePlanningInput) -> AttributePlan:
    """Prioritize new, changed, expired, and incomplete products."""
    previous = {item.product_id: item for item in planning.previous}
    products: dict[str, CatalogAttributeInput] = {}
    for product in sorted(
        planning.products,
        key=lambda item: (item.category_priority, item.product_id),
    ):
        _ = products.setdefault(product.product_id, product)
    queued: list[QueueEntry] = []
    carried: list[CarryForwardEntry] = []
    for product in products.values():
        prior = previous.get(product.product_id)
        reason = _queue_reason(product, prior, planning.observed_at)
        if reason is None:
            if prior is None:
                raise AttributeQueueError(ATTRIBUTE_ORIGIN_MISSING)
            carried.append(
                CarryForwardEntry(
                    product.product_id,
                    product.source_fingerprint_sha,
                    prior.origin_snapshot_id,
                )
            )
        else:
            queued.append(
                QueueEntry(
                    planning.catalog_generation_id,
                    product.product_id,
                    product.category_priority,
                    product.source_fingerprint_sha,
                    reason,
                )
            )
    return AttributePlan(
        tuple(queued),
        tuple(sorted(carried, key=lambda item: item.product_id)),
    )


def _queue_reason(
    product: CatalogAttributeInput,
    previous: PreviousAttribute | None,
    observed_at: datetime,
) -> QueueReason | None:
    if previous is None:
        return "new"
    if not previous.complete:
        return "never-complete"
    if product.source_fingerprint_sha != previous.source_fingerprint_sha:
        return "changed"
    if observed_at - previous.completed_at >= ATTRIBUTE_TTL:
        return "ttl"
    return None


def _require_verified(manifest: ContractManifest) -> None:
    if manifest.operation is not ATTRIBUTE_OPERATION:
        raise AttributeQueueError(QUOTA_UNVERIFIED)
    if not isinstance(manifest.state, VerifiedState):
        raise AttributeQueueError(QUOTA_UNVERIFIED)
