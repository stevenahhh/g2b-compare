"""Local adapters for deterministic index and release operations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from g2b_compare.db.connection import connect, connect_read_only
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.importers.workbook_relations import import_workbook_relations
from g2b_compare.search.index_builder import IndexBuildRequest, build_index
from g2b_compare.search.index_format import frame_members
from g2b_compare.search.index_store import IndexStore
from g2b_compare.search.models import IndexProduct
from g2b_compare.services.release import ReleaseCoordinator
from g2b_compare.services.release_models import ReleaseCandidate, ReleaseResult
from g2b_compare.services.sqlite_search import SqliteComparatorCacheBuilder

if TYPE_CHECKING:
    from pathlib import Path

EMPTY_RELATION_MANIFEST_SHA: Final = hashlib.sha256(b"empty-relations-v1").hexdigest()
EMPTY_RELATION_CONTENT_SHA: Final = hashlib.sha256(b"[]").hexdigest()


class RuntimeOperationError(RuntimeError):
    """A local operation lacks a complete persisted candidate."""

    def __init__(self, reason: str = "runtime-prerequisite-missing") -> None:
        """Initialize one stable machine-readable runtime reason."""
        super().__init__(reason)


def import_relations(database: Path, workbook: Path | None) -> tuple[int, int]:
    """Persist a verified workbook or an empty relation snapshot atomically."""
    if workbook is None:
        source_manifest_sha = EMPTY_RELATION_MANIFEST_SHA
        relation_content_sha = EMPTY_RELATION_CONTENT_SHA
        relations = ()
        quarantined_count = 0
    else:
        imported = import_workbook_relations(workbook)
        if imported.snapshot is None:
            raise RuntimeOperationError
        source_manifest_sha = imported.snapshot.source_manifest_sha
        relation_content_sha = imported.snapshot.relation_content_sha
        relations = imported.relations
        quarantined_count = len(imported.quarantined)
    with connect(database) as connection:
        _ = query(connection, "BEGIN IMMEDIATE")
        _ = query(
            connection,
            """INSERT INTO relation_snapshots VALUES(
               NULL,?,?,'building',?) ON CONFLICT(source_manifest_sha) DO NOTHING""",
            (
                source_manifest_sha,
                relation_content_sha,
                datetime.now(UTC).isoformat(),
            ),
        )
        row = query(
            connection,
            """SELECT id,status FROM relation_snapshots
               WHERE source_manifest_sha=? AND relation_content_sha=?""",
            (
                source_manifest_sha,
                relation_content_sha,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeOperationError
        snapshot_id = as_int(row[0])
        if as_text(row[1]) == "building":
            for relation in relations:
                _ = query(
                    connection,
                    """INSERT INTO curated_relations VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id,
                        relation.relation_id,
                        relation.parent_id,
                        relation.child_id,
                        relation.source_type,
                        relation.source_sha,
                        relation.sheet_name,
                        relation.row_no,
                    ),
                )
            _ = query(
                connection,
                "UPDATE relation_snapshots SET status='complete' WHERE id=?",
                (snapshot_id,),
            )
        _ = query(connection, "COMMIT")
    return len(relations), quarantined_count


def rebuild_index(database: Path, artifact: Path) -> str:
    """Build and publish the latest complete inactive materialization index."""
    with connect_read_only(database) as connection:
        identity = query(
            connection,
            """SELECT m.id,m.normalization_version
               FROM materialization_snapshots m
               WHERE m.status='complete' ORDER BY m.id DESC LIMIT 1""",
        ).fetchone()
        if identity is None:
            raise RuntimeOperationError
        materialization_id = as_int(identity[0])
        rows = query(
            connection,
            """SELECT p.product_id,p.category_no,p.detail_category_no,
                      p.product_name_raw,p.product_name_key,p.active,
                      COALESCE(group_concat(a.canonical_value,' '),'')
               FROM products p LEFT JOIN product_attributes a
                 ON a.materialization_id=p.materialization_id
                AND a.product_id=p.product_id
               WHERE p.materialization_id=?
               GROUP BY p.product_id ORDER BY p.product_id""",
            (materialization_id,),
        ).fetchall()
    products = tuple(
        IndexProduct(
            product_id=as_text(row[0]),
            category_key=(as_text(row[1]), as_text(row[2])),
            product_name_raw=as_text(row[3]),
            product_name_key=as_text(row[4]),
            option_text=as_text(row[6]),
            active=bool(as_int(row[5])),
        )
        for row in rows
    )
    bundle = build_index(
        IndexBuildRequest(
            materialization_id,
            as_text(identity[1]),
            "v1",
            "v1",
            products,
        )
    )
    store = IndexStore.create(database)
    try:
        store.publish(
            IndexBuildRequest(
                materialization_id,
                as_text(identity[1]),
                "v1",
                "v1",
                products,
            ),
            bundle,
        )
    finally:
        store.close()
    artifact.parent.mkdir(parents=True, exist_ok=True)
    _ = artifact.write_bytes(frame_members(bundle.members))
    return bundle.artifact_sha256


def precompute(database: Path) -> ReleaseResult:
    """Precompute and publish the latest complete component tuple."""
    with connect_read_only(database) as connection:
        row = query(
            connection,
            """SELECT m.id,i.id,r.id FROM materialization_snapshots m
               JOIN index_versions i ON i.materialization_id=m.id
               JOIN relation_snapshots r ON r.status='complete'
               WHERE m.status='complete' AND i.status='complete'
               ORDER BY m.id DESC,i.id DESC,r.id DESC LIMIT 1""",
        ).fetchone()
    if row is None:
        raise RuntimeOperationError
    candidate = ReleaseCandidate(
        as_int(row[0]),
        as_int(row[1]),
        as_int(row[2]),
        "v1",
    )
    builder = SqliteComparatorCacheBuilder(database, candidate)
    return ReleaseCoordinator(database, lambda: datetime.now(UTC)).coordinate(
        candidate,
        builder,
    )
