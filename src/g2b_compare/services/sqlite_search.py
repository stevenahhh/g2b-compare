"""Bridge immutable SQLite release rows to the search service contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, final

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import as_text, query
from g2b_compare.normalize.text import normalize_text
from g2b_compare.ranking.cache import CacheContractError

from .comparator_payload import (
    encode_comparator_payload,
    validate_comparator_payloads,
)
from .comparators import ComparatorCacheError, compare_product
from .release import open_release_reader, pin_active_release, read_anchor_payloads
from .sqlite_records import load_categories, load_product_records

CACHE_ANCHOR_MISSING: Final = "cache-anchor-missing"
FRESHNESS_POLICY_VERSION: Final = "freshness-v1"
MAX_DATA_AGE: Final = timedelta(days=7)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from g2b_compare.ranking.cache import CachePayload

    from .comparators import ComparatorView, ProductRecord
    from .release_models import ReleaseCandidate, ReleasePin
    from .search_models import CategoryRef


@dataclass(frozen=True, slots=True)
class _BuilderCatalog:
    by_id: Mapping[str, ProductRecord]
    by_name: Mapping[str, tuple[ProductRecord, ...]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Versioned data-age threshold with an injectable UTC clock."""

    clock: Callable[[], datetime] = _utc_now
    version: str = FRESHNESS_POLICY_VERSION
    max_age: timedelta = MAX_DATA_AGE


DEFAULT_FRESHNESS_POLICY: Final = FreshnessPolicy()


@final
class SqliteComparatorCacheBuilder:
    """Lazily project one candidate into real comparator cache payloads."""

    __slots__ = ("_candidate", "_catalog", "_database")

    def __init__(self, database: Path, candidate: ReleaseCandidate) -> None:
        """Bind cache generation to one complete candidate component tuple."""
        self._database = database
        self._candidate = candidate
        self._catalog: _BuilderCatalog | None = None

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        """Return the three canonical Ranking-v1 payloads for one anchor."""
        catalog = self._load_catalog()
        anchor = catalog.by_id.get(anchor_id)
        if anchor is None:
            raise CacheContractError(CACHE_ANCHOR_MISSING)
        views = compare_product(
            anchor,
            catalog.by_name[anchor.rankable.product_name_key],
        )
        return tuple(encode_comparator_payload(view) for view in views)

    def _load_catalog(self) -> _BuilderCatalog:
        if self._catalog is not None:
            return self._catalog
        with connect_read_only(self._database) as connection:
            products = load_product_records(
                connection,
                self._candidate,
            )
        by_name_lists: dict[str, list[ProductRecord]] = {}
        for product in products:
            by_name_lists.setdefault(
                product.rankable.product_name_key,
                [],
            ).append(product)
        self._catalog = _BuilderCatalog(
            MappingProxyType(
                {product.rankable.product_id: product for product in products}
            ),
            MappingProxyType(
                {key: tuple(values) for key, values in by_name_lists.items()}
            ),
        )
        return self._catalog


@final
class SqliteSearchReader:
    """Read products and comparator slots only through one release pin."""

    __slots__ = ("_cache_enabled", "_database", "_freshness")

    def __init__(
        self,
        database: Path,
        *,
        cache_enabled: bool = True,
        freshness: FreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
    ) -> None:
        """Select the SQLite database and optional cache fallback mode."""
        self._database = database
        self._cache_enabled = cache_enabled
        self._freshness = freshness

    def pin_active_release(self) -> ReleasePin:
        """Pin the current ready bundle and cache attempt once."""
        return pin_active_release(self._database)

    def is_stale(self, pin: ReleasePin) -> bool:
        """Apply the versioned persisted-data freshness threshold."""
        if self._freshness.version != FRESHNESS_POLICY_VERSION:
            return True
        try:
            observed = datetime.fromisoformat(pin.data_as_of)
        except ValueError:
            return True
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        now = self._freshness.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now - observed > self._freshness.max_age

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        """Read deterministic active category tuples from the materialization."""
        with open_release_reader(self._database, pin) as connection:
            return load_categories(connection, pin.materialization_id)

    def exact_products(
        self, pin: ReleasePin, product_name: str
    ) -> tuple[ProductRecord, ...]:
        """Project the exact normalized-name pool with pinned provenance."""
        name_key = normalize_text(product_name).derived
        with open_release_reader(self._database, pin) as connection:
            return load_product_records(
                connection,
                pin,
                name_key,
            )

    def cached_comparators(
        self, pin: ReleasePin, anchor_id: str
    ) -> tuple[ComparatorView, ...] | None:
        """Verify pinned payloads and return their exact comparator views."""
        if not self._cache_enabled:
            return None
        slots = read_anchor_payloads(self._database, pin, anchor_id)
        if slots is None:
            return None
        with open_release_reader(self._database, pin) as connection:
            row = query(
                connection,
                """SELECT product_name_key FROM products
                   WHERE materialization_id=? AND product_id=? AND active=1""",
                (pin.materialization_id, anchor_id),
            ).fetchone()
            if row is None:
                raise ComparatorCacheError
            products = load_product_records(
                connection,
                pin,
                as_text(row[0]),
            )
        anchor = next(
            (item for item in products if item.rankable.product_id == anchor_id),
            None,
        )
        if anchor is None:
            raise ComparatorCacheError
        return validate_comparator_payloads(anchor_id, slots, products)
