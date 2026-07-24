"""Production-search adapter over the exact perf-v1 SQLite artifact."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, ConfigDict

from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparators import (
    ComparatorScores,
    ComparatorView,
    ProductRecord,
)
from g2b_compare.services.release_models import ReleaseContractError, ReleasePin
from g2b_compare.services.search_models import CategoryRef

from .perf_index import load_pinned_perf_index
from .perf_storage import PERF_PRODUCT_COUNT, validate_perf_cache

if TYPE_CHECKING:
    from pathlib import Path

PIN_DRIFT = "perf-release-pin-drift"
INDEX_HASH_DRIFT = "perf-index-hash-drift"
INDEX_MEMBERSHIP_DRIFT = "perf-index-membership-drift"


@dataclass(frozen=True, slots=True)
class PerfReaderArtifacts:
    """Exact product and prebuilt-comparator SQLite artifact paths."""

    database: Path
    cache: Path
    index: Path


class _PerfProduct(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    product_id: str
    product_name: str
    option_text: str
    category_no: str
    detail_category_no: str
    price_won: int | None
    price_unit: str | None
    active: bool


@final
class PerfSearchReader:
    """Read exact-name pools and optional warmed comparators from perf-v1."""

    __slots__ = (
        "_cache",
        "_cache_enabled",
        "_cache_path",
        "_indexed_ids",
        "_path",
        "_pin",
    )

    def __init__(
        self,
        artifacts: PerfReaderArtifacts,
        pin: ReleasePin,
        *,
        cache_enabled: bool,
    ) -> None:
        """Bind one exact artifact and release identity for all reads."""
        self._path = artifacts.database
        self._pin = pin
        self._cache_enabled = cache_enabled
        self._cache: dict[str, tuple[ComparatorView, ...]] = {}
        self._cache_path = artifacts.cache
        index = load_pinned_perf_index(artifacts.index, pin.index_artifact_sha)
        if len(index.product_ids) != PERF_PRODUCT_COUNT:
            raise ReleaseContractError(INDEX_MEMBERSHIP_DRIFT)
        self._indexed_ids = frozenset(index.product_ids)
        if cache_enabled:
            validate_perf_cache(artifacts.cache)

    def pin_active_release(self) -> ReleasePin:
        """Return the immutable perf-v1 identity."""
        return self._pin

    def is_stale(self, pin: ReleasePin) -> bool:
        """Reject identities other than the adapter's exact artifact."""
        return pin != self._pin

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        """Return exact upper/detail tuples from the indexed artifact."""
        self._require_pin(pin)
        with sqlite3.connect(self._path) as connection:
            rows = query(
                connection,
                """SELECT DISTINCT category_no, detail_category_no
                   FROM products ORDER BY category_no, detail_category_no""",
            ).fetchall()
        return tuple(CategoryRef(as_text(row[0]), as_text(row[1])) for row in rows)

    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        """Project one indexed exact-name pool into production records."""
        self._require_pin(pin)
        with sqlite3.connect(self._path) as connection:
            rows = query(
                connection,
                """SELECT payload FROM products
                   WHERE product_name = ? ORDER BY product_id""",
                (product_name,),
            ).fetchall()
        products = tuple(
            _record(_PerfProduct.model_validate_json(as_text(row[0]))) for row in rows
        )
        if any(
            product.rankable.product_id not in self._indexed_ids for product in products
        ):
            raise ReleaseContractError(INDEX_MEMBERSHIP_DRIFT)
        return products

    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        """Return warmed comparator views only in the cache-enabled scenario."""
        self._require_pin(pin)
        if not self._cache_enabled:
            return None
        return self._cache.get(anchor_id)

    def warm_cache(self, product_name: str) -> int:
        """Precompute the same typed comparator views used by search responses."""
        products = self.exact_products(self._pin, product_name)
        by_id = {product.rankable.product_id: product for product in products}
        prefix = products[0].rankable.product_id.rsplit("-", maxsplit=1)[0] + "-%"
        with sqlite3.connect(self._cache_path) as connection:
            rows = query(
                connection,
                """SELECT anchor_id, slot, candidate_id
                   FROM comparator_cache WHERE anchor_id LIKE ?
                   ORDER BY anchor_id, slot""",
                (prefix,),
            ).fetchall()
        grouped: dict[str, list[ComparatorView]] = {}
        for row in rows:
            anchor_id = as_text(row[0])
            slot = as_int(row[1])
            candidate = by_id[as_text(row[2])]
            score = Decimal(10 - slot) / Decimal(10)
            view = ComparatorView(
                anchor_id,
                slot,
                "ok",
                candidate,
                ComparatorScores(score, score, score, score, score, Decimal(1)),
                (),
                (),
            )
            grouped.setdefault(anchor_id, []).append(view)
        self._cache = {anchor_id: tuple(views) for anchor_id, views in grouped.items()}
        return len(self._cache)

    def _require_pin(self, pin: ReleasePin) -> None:
        if pin != self._pin:
            raise ReleaseContractError(PIN_DRIFT)


def perf_release_pin(
    *,
    database_sha256: str,
    index_sha256: str,
    cache_sha256: str,
) -> ReleasePin:
    """Create the immutable release identity embedded in benchmark responses."""
    return ReleasePin(
        1,
        1,
        1,
        1,
        1,
        "v1",
        "normalization-v1",
        "perf-v1",
        database_sha256,
        index_sha256,
        index_sha256,
        cache_sha256,
        cache_sha256,
        "2026-07-14T00:00:00Z",
    )


def _record(source: _PerfProduct) -> ProductRecord:
    price_active = (
        source.price_won is not None
        and source.price_won > 0
        and source.price_unit is not None
    )
    rankable = RankableProduct(
        source.product_id,
        (source.category_no, source.detail_category_no),
        source.product_name,
        source.option_text,
        source.active,
        ComparisonPrice(
            price_active,
            source.price_won,
            source.price_unit,
            ("perf-v1", source.product_id) if price_active else None,
            None if price_active else "missing-price",
        ),
    )
    return ProductRecord(rankable, source.product_name, "2026-07-14", "3/3", (), ())
