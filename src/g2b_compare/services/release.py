"""Atomic release cache precomputation and pointer publication."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final, assert_never, final

from g2b_compare.db.release import ReleaseStore
from g2b_compare.db.release_types import (
    BundleRecord,
    BundleStatus,
    ReleaseKey,
    ReleaseStoreError,
)
from g2b_compare.ranking.cache import (
    CacheContractError,
    CacheRow,
)

from .release_models import (
    ComparatorCacheBuilder,
    ReleaseCandidate,
    ReleaseContractError,
    ReleaseDisposition,
    ReleasePin,
    ReleaseResult,
)
from .release_reader import (
    open_release_reader,
    pin_active_release,
    pin_release_bundle,
    read_anchor_payloads,
)

__all__ = (
    "ComparatorCacheBuilder",
    "ReleaseCandidate",
    "ReleaseContractError",
    "ReleaseCoordinator",
    "ReleaseDisposition",
    "ReleasePin",
    "ReleaseResult",
    "open_release_reader",
    "pin_active_release",
    "read_anchor_payloads",
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path


FAILED_RETRY: Final = "failed-attempt-not-retried"


@final
class ReleaseCoordinator:
    """Build inactive attempt caches and atomically publish one ready bundle."""

    def __init__(self, database: Path, clock: Callable[[], datetime]) -> None:
        """Initialize one database and deterministic clock boundary."""
        self._database = database
        self._clock = clock

    def coordinate(
        self,
        candidate: ReleaseCandidate,
        builder: ComparatorCacheBuilder,
    ) -> ReleaseResult:
        """Coordinate one idempotent release attempt."""
        key = ReleaseKey(
            candidate.materialization_id,
            candidate.index_version_id,
            candidate.relation_snapshot_id,
            candidate.ranking_version,
            candidate.slot_policy_version,
        )
        store = ReleaseStore(self._database)
        now = self._clock()
        try:
            record = store.claim(key, now, now - timedelta(minutes=10))
            match record.status:
                case BundleStatus.READY:
                    store.verify_ready(key, record)
                    return ReleaseResult(
                        ReleaseDisposition.READY_NOOP,
                        record.bundle_id,
                        record.attempt_no,
                        pin_release_bundle(self._database, record.bundle_id),
                    )
                case BundleStatus.BUILDING if not record.owned:
                    return ReleaseResult(
                        ReleaseDisposition.BUILDING_NOOP,
                        record.bundle_id,
                        record.attempt_no,
                        None,
                    )
                case BundleStatus.BUILDING:
                    return self._build(store, key, record, builder)
                case BundleStatus.FAILED:
                    raise ReleaseContractError(FAILED_RETRY)
                case _:
                    assert_never(record.status)
        except ReleaseStoreError as error:
            raise ReleaseContractError(error.code) from error

    def _build(
        self,
        store: ReleaseStore,
        key: ReleaseKey,
        record: BundleRecord,
        builder: ComparatorCacheBuilder,
    ) -> ReleaseResult:
        try:
            components = store.components(key)
            anchors = store.anchors(key.materialization_id)
            store.set_expected(record, len(anchors) * 3, self._clock())
            next_heartbeat = self._clock() + timedelta(seconds=30)
            for anchor in anchors:
                for slot, payload in enumerate(builder.slots_for(anchor), start=1):
                    store.write(record, CacheRow(anchor, slot, payload))
                if self._clock() >= next_heartbeat:
                    store.heartbeat(record, self._clock())
                    next_heartbeat = self._clock() + timedelta(seconds=30)
            store.publish(key, record, components, self._clock())
        except (ReleaseStoreError, CacheContractError) as error:
            store.fail(record, self._clock())
            raise ReleaseContractError(error.code) from error
        pin = pin_release_bundle(self._database, record.bundle_id)
        return ReleaseResult(
            ReleaseDisposition.READY,
            record.bundle_id,
            record.attempt_no,
            pin,
        )
