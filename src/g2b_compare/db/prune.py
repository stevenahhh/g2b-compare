"""Raw-blob retention reachability queries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .connection import connect
from .sql import as_text, query


@dataclass(frozen=True, slots=True)
class RawRetentionRepository:
    """Determines protected raw bodies and removes only unreferenced blobs."""

    database: Path

    def protected_body_shas(self) -> frozenset[str]:
        """Return raw bodies reachable from every web-visible origin."""
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                WITH RECURSIVE
                source_ancestors(id) AS (
                    SELECT snapshot_id FROM active_source_snapshots
                    UNION
                    SELECT source_snapshots.parent_id
                    FROM source_snapshots
                    JOIN source_ancestors ON source_snapshots.id = source_ancestors.id
                    WHERE source_snapshots.parent_id IS NOT NULL
                ),
                attribute_ancestors(id) AS (
                    SELECT snapshot_id FROM active_attribute_snapshots
                    UNION
                    SELECT materialization_snapshots.attribute_snapshot_id
                    FROM active_release
                    JOIN release_bundles
                      ON release_bundles.id = active_release.bundle_id
                    JOIN materialization_snapshots ON materialization_snapshots.id =
                        release_bundles.materialization_id
                    UNION
                    SELECT attribute_snapshots.parent_id
                    FROM attribute_snapshots
                    JOIN attribute_ancestors
                      ON attribute_snapshots.id = attribute_ancestors.id
                    WHERE attribute_snapshots.parent_id IS NOT NULL
                ),
                protected_pages(id) AS (
                    SELECT origin_page_id FROM source_records
                    WHERE source_snapshot_id IN (SELECT id FROM source_ancestors)
                    UNION
                    SELECT origin_page_id FROM attribute_records
                    WHERE attribute_snapshot_id IN (SELECT id FROM attribute_ancestors)
                    UNION
                    SELECT sync_pages.id FROM sync_pages
                    JOIN sync_runs ON sync_runs.id = sync_pages.run_id
                    WHERE sync_runs.status = 'failed'
                      AND sync_runs.id IN (
                          SELECT MAX(id) FROM sync_runs
                          WHERE status = 'failed' GROUP BY operation
                      )
                )
                SELECT DISTINCT body_sha FROM sync_pages
                WHERE id IN (SELECT id FROM protected_pages)
                """,
            ).fetchall()
        return frozenset(as_text(row[0]) for row in rows)

    def prune_unreferenced(self, cutoff_created_at: str) -> tuple[Path, ...]:
        """Delete old raw files that have no page or protected origin."""
        protected = self.protected_body_shas()
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                SELECT body_sha, raw_path FROM raw_blobs
                WHERE created_at < ?
                  AND body_sha NOT IN (SELECT body_sha FROM sync_pages)
                ORDER BY body_sha
                """,
                (cutoff_created_at,),
            ).fetchall()
            paths = tuple(
                Path(as_text(row[1]))
                for row in rows
                if as_text(row[0]) not in protected
            )
            for path in paths:
                path.unlink(missing_ok=True)
            for row in rows:
                body_sha = as_text(row[0])
                if body_sha not in protected:
                    _ = query(
                        connection,
                        "DELETE FROM raw_blobs WHERE body_sha = ?",
                        (body_sha,),
                    )
        return paths
