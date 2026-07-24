"""Serve one request-scoped live search reader with no local accumulation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final

from g2b_compare.normalize.units import NORMALIZATION_VERSION
from g2b_compare.ranking.formula import RANKING_VERSION
from g2b_compare.services.live_pool import LivePool, fetch_live_pool
from g2b_compare.services.release_models import ReleasePin

if TYPE_CHECKING:
    from collections.abc import Callable

    from g2b_compare.services.comparator_models import ProductRecord
    from g2b_compare.services.comparators import ComparatorView
    from g2b_compare.services.search_models import CategoryRef
    from g2b_compare.sources.shopping_mall import ShoppingMallAdapter

_SENTINEL_SHA: Final = "0" * 64


@final
class LiveReaderNotPinnedError(Exception):
    """Report a categories()/exact_products() call before pin_active_release()."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@final
class WebLiveSearchReader:
    """Fetch one product name from the live G2B API, once per request."""

    __slots__ = (
        "_adapter",
        "_clock",
        "_pool",
        "_product_name",
        "_service_key",
        "_source_page",
    )

    def __init__(
        self,
        product_name: str,
        adapter: ShoppingMallAdapter,
        service_key: str,
        *,
        source_page: int = 1,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Bind the exact name this instance is scoped to serve."""
        self._product_name = product_name
        self._adapter = adapter
        self._service_key = service_key
        self._source_page = source_page
        self._clock = clock
        self._pool: LivePool | None = None

    def pin_active_release(self) -> ReleasePin:
        """Fetch the live pool once and pin it as this request's release."""
        if self._pool is None:
            self._pool = fetch_live_pool(
                self._adapter,
                self._service_key,
                self._product_name,
                self._clock(),
                source_page=self._source_page,
            )
        observed_at = self._clock().isoformat()
        return ReleasePin(
            bundle_id=0,
            ready_attempt_no=0,
            materialization_id=0,
            index_version_id=0,
            relation_snapshot_id=0,
            ranking_version=RANKING_VERSION,
            normalization_version=NORMALIZATION_VERSION,
            materialization_policy_version="live-v1",
            materialization_source_sha=_SENTINEL_SHA,
            index_artifact_sha=_SENTINEL_SHA,
            index_manifest_sha=_SENTINEL_SHA,
            relation_source_manifest_sha=_SENTINEL_SHA,
            relation_content_sha=_SENTINEL_SHA,
            data_as_of=observed_at,
        )

    def is_stale(self, pin: ReleasePin) -> bool:
        """Live data is fetched fresh on every request; it cannot go stale."""
        del pin
        return False

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        """Read the category tuples observed in this request's live pool."""
        del pin
        return self._require_pool().categories

    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        """Read the products fetched for this instance's bound product name."""
        del pin, product_name
        return self._require_pool().products

    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        """Report no cache; comparators are always computed fresh."""
        del pin, anchor_id
        return None

    @property
    def truncated(self) -> bool:
        """Report whether the per-operation page cap was reached."""
        return self._require_pool().truncated

    @property
    def has_next(self) -> bool:
        """Report whether any provider operation has another page."""
        return self._require_pool().has_next

    @property
    def product_order(self) -> tuple[str, ...]:
        """Expose the provider order after deterministic product de-duplication."""
        return tuple(
            product.rankable.product_id for product in self._require_pool().products
        )

    def _require_pool(self) -> LivePool:
        if self._pool is None:
            raise LiveReaderNotPinnedError
        return self._pool
