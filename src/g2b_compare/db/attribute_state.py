"""Attribute fingerprint and retry queue persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .repository import RepositoryContractError
from .sql import as_int, as_text, query

if TYPE_CHECKING:
    import sqlite3

    from .models import AttributeStateInput


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """One product fingerprint bound to a catalog generation."""

    catalog_id: int
    product_id: str
    sha: str


def catalog_id(connection: sqlite3.Connection, snapshot_id: int) -> int:
    """Resolve an attribute snapshot's catalog generation."""
    row = query(
        connection,
        "SELECT catalog_generation_id FROM attribute_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise RepositoryContractError(detail="attribute snapshot missing")
    return as_int(row[0])


def fingerprint(
    connection: sqlite3.Connection, catalog_id: int, product_id: str
) -> str | None:
    """Return a catalog product fingerprint when recorded."""
    row = query(
        connection,
        """SELECT fingerprint_sha FROM product_source_fingerprints
        WHERE catalog_generation_id = ? AND product_id = ?""",
        (catalog_id, product_id),
    ).fetchone()
    return None if row is None else as_text(row[0])


def record_fingerprint(
    connection: sqlite3.Connection, fingerprint: Fingerprint
) -> None:
    """Persist the canonical fingerprint for one catalog product."""
    _ = query(
        connection,
        """INSERT INTO product_source_fingerprints VALUES (?, ?, ?)
        ON CONFLICT(catalog_generation_id, product_id)
        DO UPDATE SET fingerprint_sha = excluded.fingerprint_sha""",
        (fingerprint.catalog_id, fingerprint.product_id, fingerprint.sha),
    )


def enqueue(connection: sqlite3.Connection, catalog_id: int, product_id: str) -> None:
    """Place a product in the current catalog's retry queue."""
    _ = query(
        connection,
        """INSERT INTO attribute_enrichment_queue
        VALUES (?, ?, 'pending', 0, 0, '', NULL)
        ON CONFLICT(catalog_generation_id, product_id)
        DO UPDATE SET status = 'pending'""",
        (catalog_id, product_id),
    )


def clear_queue(
    connection: sqlite3.Connection, catalog_id: int, product_id: str
) -> None:
    """Remove a product from the current catalog's retry queue."""
    _ = query(
        connection,
        """DELETE FROM attribute_enrichment_queue
        WHERE catalog_generation_id = ? AND product_id = ?""",
        (catalog_id, product_id),
    )


def upsert_state(
    connection: sqlite3.Connection,
    snapshot_id: int,
    state: AttributeStateInput,
) -> None:
    """Persist one product state in an attribute snapshot."""
    _ = query(
        connection,
        """INSERT INTO attribute_product_states(
            attribute_snapshot_id, product_id, fetch_status,
            source_fingerprint_sha, completed_at, origin_snapshot_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(attribute_snapshot_id, product_id) DO UPDATE SET
            fetch_status = excluded.fetch_status,
            source_fingerprint_sha = excluded.source_fingerprint_sha,
            completed_at = excluded.completed_at,
            origin_snapshot_id = excluded.origin_snapshot_id""",
        (
            snapshot_id,
            state.product_id,
            state.fetch_status,
            state.source_fingerprint_sha,
            state.completed_at,
            state.origin_snapshot_id,
        ),
    )
