from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from g2b_compare.contracts.quota import Operation
from g2b_compare.sync.catalog import advance_catalog
from g2b_compare.sync.paginator import SyncInvariantError
from g2b_compare.sync.publisher import SourceDelta
from tests.sync.todo8_failure_cases import observe_case
from tests.sync.todo8_fixture import (
    NOW,
    add_page,
    complete_products,
    database,
    publish,
    record,
    release_bytes,
    setup_five_sources,
)
from tests.sync.todo8_review_support import independent_states, seed_ready_release_on

if TYPE_CHECKING:
    from datetime import date, datetime
    from pathlib import Path


class FailureObservation(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    assertion_class: str
    message: str
    operation: str


@dataclass(frozen=True, slots=True)
class HappyObservation:
    source_count: int
    delivery_delta_carried: tuple[str, ...]
    partial_successor_pending: tuple[str, ...]
    resumed_digest: str
    uninterrupted_digest: str
    release_before: bytes
    release_after: bytes


def run_happy(path: Path, today: date) -> HappyObservation:
    _ = today
    db = database(path)
    setup_five_sources(db)
    first = advance_catalog(path, NOW)
    attribute_id = complete_products(db, first, ("P-1",))
    seed_ready_release_on(db, first.catalog_generation_id, attribute_id)
    release_before = release_bytes(db)
    delivery_page = add_page(db, Operation.GET_DELIVERY_REQUEST_DETAIL.value, "delta")
    _ = publish(
        db,
        Operation.GET_DELIVERY_REQUEST_DETAIL,
        "delta",
        (SourceDelta(record("D-1", "P-1", delivery_page, "e")),),
    )
    delivery = advance_catalog(path, NOW)
    offer_page = add_page(db, Operation.GET_MAS_CONTRACT_PRODUCT_INFO.value, "new")
    _ = publish(
        db,
        Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        "delta",
        (SourceDelta(record("K-2", "P-2", offer_page, "b")),),
    )
    partial = advance_catalog(path, NOW)
    uninterrupted, resumed = independent_states(path.parent, mutate_resumed=False)
    return HappyObservation(
        5,
        delivery.carried_products,
        partial.queued_products,
        sha256(resumed).hexdigest(),
        sha256(uninterrupted).hexdigest(),
        release_before,
        release_bytes(db),
    )


def observe_failure(scenario: str, path: Path, now: datetime) -> FailureObservation:
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    try:
        message = observe_case(scenario, path, now)
    except SyncInvariantError as error:
        return FailureObservation(
            assertion_class=type(error).__name__,
            message=str(error),
            operation=operation.value,
        )
    return FailureObservation(
        assertion_class="Todo8Observation",
        message=message,
        operation=operation.value,
    )
