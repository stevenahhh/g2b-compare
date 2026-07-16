"""Persistent attribute queue and atomic fetch publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.db.connection import connect
from g2b_compare.db.models import AttributeStateInput
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sync.attribute_persistence import publish_complete_fetch
from g2b_compare.sync.attribute_queue_state import (
    ApplyResult,
    AttributePlan,
    AttributeQueueError,
    CarryForwardEntry,
    CatalogAttributeInput,
    CompleteFetch,
    DispatchBudget,
    FailedFetch,
    FetchCommit,
    PreviousAttribute,
    QueueEntry,
    QueuePlanningInput,
    QuotaWindow,
    dispatch_budget,
    plan_attribute_queue,
)
from g2b_compare.sync.attribute_quota import AttributeQuotaError, AttributeQuotaGate

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from g2b_compare.db.lifecycle import AttributeRepository

CATALOG_MISMATCH: Final = "catalog-generation-mismatch"
NO_DATA_INCOMPLETE: Final = "no-data-not-complete-empty"
REPOSITORY_MISMATCH: Final = "attribute-repository-mismatch"
CARRY_DRIFT: Final = "attribute-carry-drift"
SNAPSHOT_MISSING: Final = "attribute-snapshot-missing"

__all__ = (
    "ApplyResult",
    "AttributePlan",
    "AttributeQueueError",
    "AttributeQueueStore",
    "AttributeQuotaError",
    "AttributeQuotaGate",
    "CarryForwardEntry",
    "CatalogAttributeInput",
    "CompleteFetch",
    "DispatchBudget",
    "FailedFetch",
    "FetchCommit",
    "PreviousAttribute",
    "QueueEntry",
    "QueuePlanningInput",
    "QuotaWindow",
    "apply_fetch",
    "dispatch_budget",
    "plan_attribute_queue",
)


@dataclass(frozen=True, slots=True)
class AttributeQueueStore:
    """SQLite-backed idempotent queue persistence."""

    database: Path

    def seed(self, generation_id: int, entries: tuple[QueueEntry, ...]) -> None:
        """Persist deduplicated queue and fingerprint state."""
        with connect(self.database) as connection:
            for entry in entries:
                if entry.catalog_generation_id != generation_id:
                    raise AttributeQueueError(CATALOG_MISMATCH)
                _ = query(
                    connection,
                    """INSERT INTO attribute_enrichment_queue
                    VALUES (?, ?, 'pending', ?, 0, '', NULL)
                    ON CONFLICT(catalog_generation_id, product_id) DO NOTHING""",
                    (generation_id, entry.product_id, entry.category_priority),
                )
                _ = query(
                    connection,
                    """INSERT INTO product_source_fingerprints VALUES (?, ?, ?)
                    ON CONFLICT(catalog_generation_id, product_id)
                    DO UPDATE SET fingerprint_sha = excluded.fingerprint_sha""",
                    (generation_id, entry.product_id, entry.source_fingerprint_sha),
                )

    def ready(
        self,
        generation_id: int,
        observed_at: datetime,
        limit: int,
    ) -> tuple[QueueEntry, ...]:
        """Read a deterministic ready prefix after restart."""
        with connect(self.database) as connection:
            rows = query(
                connection,
                """SELECT queue.product_id, queue.priority, fingerprints.fingerprint_sha
                FROM attribute_enrichment_queue AS queue
                JOIN product_source_fingerprints AS fingerprints
                  ON fingerprints.catalog_generation_id = queue.catalog_generation_id
                 AND fingerprints.product_id = queue.product_id
                WHERE queue.catalog_generation_id = ? AND queue.status = 'pending'
                  AND queue.next_attempt_at <= ?
                ORDER BY queue.priority, queue.product_id LIMIT ?""",
                (generation_id, observed_at.isoformat(), limit),
            ).fetchall()
        return tuple(
            QueueEntry(
                generation_id,
                as_text(row[0]),
                as_int(row[1]),
                as_text(row[2]),
                "new",
            )
            for row in rows
        )

    def persist_plan(
        self,
        repository: AttributeRepository,
        successor_snapshot_id: int,
        plan: AttributePlan,
    ) -> None:
        """Persist queued and origin-preserving carry decisions restartably."""
        if repository.database != self.database:
            raise AttributeQueueError(REPOSITORY_MISMATCH)
        self.seed(
            plan.queued[0].catalog_generation_id
            if plan.queued
            else _catalog_id(
                self.database,
                successor_snapshot_id,
            ),
            plan.queued,
        )
        successor_catalog = _catalog_id(self.database, successor_snapshot_id)
        for carried in plan.carried:
            repository.record_product_fingerprint(
                successor_catalog,
                carried.product_id,
                carried.source_fingerprint_sha,
            )
            with connect(self.database) as connection:
                row = query(
                    connection,
                    """SELECT fetch_status, source_fingerprint_sha,
                              origin_snapshot_id
                    FROM attribute_product_states
                    WHERE attribute_snapshot_id = ? AND product_id = ?""",
                    (successor_snapshot_id, carried.product_id),
                ).fetchone()
            if row is not None:
                expected = (
                    "carried-forward",
                    carried.source_fingerprint_sha,
                    carried.origin_snapshot_id,
                )
                if (as_text(row[0]), as_text(row[1]), as_int(row[2])) != expected:
                    raise AttributeQueueError(CARRY_DRIFT)
                continue
            repository.carry_forward_product(
                carried.origin_snapshot_id,
                successor_snapshot_id,
                carried.product_id,
            )


def apply_fetch(repository: AttributeRepository, commit: FetchCommit) -> ApplyResult:
    """Publish complete rows or retain old rows on every failure."""
    if commit.expected_generation_id != commit.current_generation_id:
        return "raw-only"
    if isinstance(commit.outcome, CompleteFetch):
        records = commit.outcome.records
        if not records and not commit.outcome.official_no_data:
            raise AttributeQueueError(NO_DATA_INCOMPLETE)
        publish_complete_fetch(repository.database, commit, commit.outcome)
        return "applied"
    repository.set_state(
        commit.snapshot_id,
        AttributeStateInput(
            commit.product_id,
            "failed",
            commit.source_fingerprint_sha,
            None,
            commit.origin_snapshot_id,
        ),
    )
    return "retained"


def _catalog_id(database: Path, snapshot_id: int) -> int:
    with connect(database) as connection:
        row = query(
            connection,
            "SELECT catalog_generation_id FROM attribute_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
    if row is None:
        raise AttributeQueueError(SNAPSHOT_MISSING)
    return as_int(row[0])
