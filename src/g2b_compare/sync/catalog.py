"""Five-source catalog transition and generation-scoped attribute successor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.models import AttributeStateInput
from g2b_compare.db.repository import DatabaseRepository
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sync.attribute_queue import AttributeQueueStore
from g2b_compare.sync.attribute_queue_state import QueueEntry
from g2b_compare.sync.paginator import SyncInvariantError

if TYPE_CHECKING:
    from pathlib import Path

OFFER_OPERATIONS: Final = tuple(Operation)[:3]
FINGERPRINT_OPERATIONS: Final = tuple(Operation)[:4]
SOURCE_OPERATIONS: Final = tuple(Operation)[:5]
FIVE_SOURCE_SET_INCOMPLETE: Final = "five-source-set-incomplete"


@dataclass(frozen=True, slots=True)
class CatalogAdvance:
    """Observable catalog and attribute successor publication result."""

    catalog_generation_id: int
    attribute_snapshot_id: int
    carried_products: tuple[str, ...]
    queued_products: tuple[str, ...]
    active_products: tuple[str, ...]


def advance_catalog(database: Path, published_at: str) -> CatalogAdvance:
    """Create a generation only for the exact active five-source set."""
    source_ids = _source_ids(database)
    previous_catalog = _latest_catalog(database)
    catalog_id = DatabaseRepository(database).create_catalog_generation(
        source_ids,
        published_at,
    )
    existing_attribute = _active_attribute(database, catalog_id)
    if existing_attribute is not None:
        return CatalogAdvance(
            catalog_id,
            existing_attribute,
            (),
            (),
            _active_products(database),
        )
    active_products = _active_products(database)
    fingerprints = _fingerprints(database, active_products)
    parent_attribute = _active_attribute(database, previous_catalog)
    attribute_repository = AttributeRepository(database)
    snapshot_id = attribute_repository.create_snapshot(
        catalog_id,
        parent_attribute,
        len(active_products),
    )
    carried: list[str] = []
    queued: list[str] = []
    entries: list[QueueEntry] = []
    for product_id in active_products:
        fingerprint = fingerprints[product_id]
        attribute_repository.record_product_fingerprint(
            catalog_id,
            product_id,
            fingerprint,
        )
        if parent_attribute is not None and _can_carry(
            database,
            previous_catalog,
            parent_attribute,
            product_id,
            fingerprint,
        ):
            attribute_repository.carry_forward_product(
                parent_attribute,
                snapshot_id,
                product_id,
            )
            carried.append(product_id)
            continue
        attribute_repository.set_state(
            snapshot_id,
            AttributeStateInput(
                product_id,
                "pending",
                fingerprint,
                None,
                parent_attribute,
            ),
        )
        queued.append(product_id)
        entries.append(QueueEntry(catalog_id, product_id, 0, fingerprint, "changed"))
    AttributeQueueStore(database).seed(catalog_id, tuple(entries))
    attribute_repository.publish_snapshot(snapshot_id, published_at)
    return CatalogAdvance(
        catalog_id,
        snapshot_id,
        tuple(carried),
        tuple(queued),
        active_products,
    )


def product_is_active(database: Path, product_id: str) -> bool:
    """Return true while any of the three offer operations remains active."""
    return product_id in _active_products(database)


def _source_ids(database: Path) -> tuple[tuple[str, int], ...]:
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT operation, snapshot_id
               FROM active_source_snapshots ORDER BY operation""",
        ).fetchall()
    source_ids = tuple((as_text(row[0]), as_int(row[1])) for row in rows)
    if {item[0] for item in source_ids} != {item.value for item in SOURCE_OPERATIONS}:
        raise SyncInvariantError(FIVE_SOURCE_SET_INCOMPLETE)
    return source_ids


def _latest_catalog(database: Path) -> int | None:
    with connect(database) as connection:
        row = query(connection, "SELECT MAX(id) FROM catalog_generations").fetchone()
    if row is None or row[0] is None:
        return None
    return as_int(row[0])


def _active_attribute(database: Path, catalog_id: int | None) -> int | None:
    if catalog_id is None:
        return None
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT snapshot_id FROM active_attribute_snapshots
               WHERE catalog_generation_id = ?""",
            (catalog_id,),
        ).fetchone()
    return None if row is None else as_int(row[0])


def _active_products(database: Path) -> tuple[str, ...]:
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT DISTINCT records.product_id
                FROM active_source_snapshots AS active
                JOIN source_records AS records
                  ON records.source_snapshot_id = active.snapshot_id
                 AND records.operation = active.operation
                WHERE active.operation IN (?, ?, ?)
                  AND records.is_tombstone = 0
                ORDER BY records.product_id""",
            tuple(item.value for item in OFFER_OPERATIONS),
        ).fetchall()
    return tuple(as_text(row[0]) for row in rows)


def _fingerprints(database: Path, products: tuple[str, ...]) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    with connect(database) as connection:
        for product_id in products:
            rows = query(
                connection,
                """SELECT records.operation, records.source_record_key,
                          records.canonical_record_sha
                   FROM active_source_snapshots AS active
                   JOIN source_records AS records
                     ON records.source_snapshot_id = active.snapshot_id
                    AND records.operation = active.operation
                   WHERE records.product_id = ? AND records.is_tombstone = 0
                   ORDER BY records.operation, records.source_record_key""",
                (product_id,),
            ).fetchall()
            values = tuple(
                (as_text(row[0]), as_text(row[1]), as_text(row[2]))
                for row in rows
                if as_text(row[0]) in {item.value for item in FINGERPRINT_OPERATIONS}
            )
            encoded = json.dumps(values, separators=(",", ":"))
            fingerprints[product_id] = hashlib.sha256(encoded.encode()).hexdigest()
    return fingerprints


def _can_carry(
    database: Path,
    previous_catalog: int | None,
    parent_attribute: int,
    product_id: str,
    fingerprint: str,
) -> bool:
    if previous_catalog is None:
        return False
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT fingerprints.fingerprint_sha, states.fetch_status
               FROM product_source_fingerprints AS fingerprints
               JOIN attribute_product_states AS states
                 ON states.product_id = fingerprints.product_id
                AND states.attribute_snapshot_id = ?
               WHERE fingerprints.catalog_generation_id = ?
                 AND fingerprints.product_id = ?""",
            (parent_attribute, previous_catalog, product_id),
        ).fetchone()
    return (
        row is not None
        and as_text(row[0]) == fingerprint
        and as_text(row[1])
        in (
            "complete-nonempty",
            "complete-empty",
            "carried-forward",
        )
    )
