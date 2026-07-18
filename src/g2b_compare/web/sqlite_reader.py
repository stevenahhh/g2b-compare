"""Expose persisted SQLite health without suppressing last-good search rows."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final, final

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import as_text, query
from g2b_compare.services.sqlite_search import SqliteSearchReader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from g2b_compare.services.comparator_models import ProductRecord
    from g2b_compare.services.comparators import ComparatorView
    from g2b_compare.services.release_models import ReleasePin
    from g2b_compare.services.search_models import CategoryRef

_LATEST_SYNC_PARTS: Final = (
    "SELECT current.status FROM sync_runs AS current",
    "WHERE NOT EXISTS(",
    "SELECT 1 FROM sync_runs AS newer",
    "WHERE newer.operation=current.operation AND newer.id>current.id",
    ")",
)
_LATEST_SOURCE_PARTS: Final = (
    "SELECT current.status FROM source_snapshots AS current",
    "WHERE NOT EXISTS(",
    "SELECT 1 FROM source_snapshots AS newer",
    "WHERE newer.operation=current.operation AND newer.id>current.id",
    ")",
)
_ATTRIBUTE_STATE_PARTS: Final = (
    "SELECT fetch_status FROM attribute_product_states",
    "WHERE attribute_snapshot_id=(",
    "SELECT MAX(id) FROM attribute_snapshots",
    ")",
)
_LATEST_STATUS_QUERIES: Final = (
    " ".join(_LATEST_SYNC_PARTS),
    " ".join(_LATEST_SOURCE_PARTS),
    "SELECT status FROM attribute_snapshots ORDER BY id DESC LIMIT 1",
    "SELECT status FROM materialization_snapshots ORDER BY id DESC LIMIT 1",
    "SELECT status FROM index_versions ORDER BY id DESC LIMIT 1",
    "SELECT status FROM relation_snapshots ORDER BY id DESC LIMIT 1",
    "SELECT status FROM release_bundles ORDER BY created_at DESC,id DESC LIMIT 1",
    " ".join(_ATTRIBUTE_STATE_PARTS),
)
_FAILED_STATUSES: Final = frozenset({"failed"})
_KST: Final = timezone(timedelta(hours=9))
_SOURCE_MAX_LAG: Final = timedelta(days=2)
_SYNC_MAX_AGE: Final = timedelta(hours=36)
_ACTIVE_SOURCE_DATES: Final = """
    SELECT products.data_as_of
    FROM active_release AS active
    JOIN release_bundles AS bundles ON bundles.id=active.bundle_id
    JOIN products ON products.materialization_id=bundles.materialization_id
    WHERE active.singleton=1 AND products.active=1
"""
_SUCCESSFUL_SYNCS: Final = """
    SELECT finished_at
    FROM sync_runs
    WHERE status IN ('complete','completed') AND finished_at IS NOT NULL
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@final
class WebSqliteSearchReader:
    """Serve pinned rows while projecting freshness and failed successors."""

    __slots__ = ("_clock", "_database", "_reader")

    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Bind one read-only production database."""
        self._clock = clock
        self._database = database
        self._reader = SqliteSearchReader(database)

    def pin_active_release(self) -> ReleasePin:
        """Pin the active last-good release."""
        return self._reader.pin_active_release()

    def is_stale(self, pin: ReleasePin) -> bool:
        """Keep last-good rows searchable; expose staleness via web statuses."""
        del pin
        return False

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        """Read categories from the pinned release."""
        return self._reader.categories(pin)

    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        """Read exact products from the pinned release."""
        return self._reader.exact_products(pin, product_name)

    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        """Read comparator slots from the pinned release."""
        return self._reader.cached_comparators(pin, anchor_id)

    def web_statuses(self, _release: ReleasePin) -> tuple[str, ...]:
        """Return exact persisted freshness and sync-failure predicates."""
        statuses: list[str] = []
        if _production_is_stale(self._database, self._clock()):
            statuses.append("stale")
        if _latest_failed(self._database):
            statuses.append("sync-failed-last-good")
        return tuple(sorted(statuses, key=str.encode))


def _latest_failed(database: Path) -> bool:
    with connect_read_only(database) as connection:
        for statement in _LATEST_STATUS_QUERIES:
            rows = query(connection, statement).fetchall()
            if any(as_text(row[0]) in _FAILED_STATUSES for row in rows):
                return True
    return False


def _production_is_stale(database: Path, now: datetime) -> bool:
    with connect_read_only(database) as connection:
        source_rows = query(connection, _ACTIVE_SOURCE_DATES).fetchall()
        sync_rows = query(connection, _SUCCESSFUL_SYNCS).fetchall()
    if not source_rows or not sync_rows:
        return True
    normalized_now = _as_utc(now)
    cutoff = normalized_now.astimezone(_KST).date() - _SOURCE_MAX_LAG
    try:
        source_dates = tuple(_as_kst_date(as_text(row[0])) for row in source_rows)
        successful_at = tuple(_as_utc_text(as_text(row[0])) for row in sync_rows)
    except ValueError:
        return True
    sources_current = all(observed >= cutoff for observed in source_dates)
    sync_current = normalized_now - max(successful_at) <= _SYNC_MAX_AGE
    return not (sources_current and sync_current)


def _as_kst_date(value: str) -> date:
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        return observed.date()
    return observed.astimezone(_KST).date()


def _as_utc_text(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
