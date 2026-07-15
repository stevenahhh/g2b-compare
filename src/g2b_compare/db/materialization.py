"""Idempotent materialization identity persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from .connection import connect
from .hashes import materialization_source_sha
from .repository import RepositoryContractError
from .sql import as_int, as_text, query

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_MAP_ADAPTER: Final = TypeAdapter(dict[str, int])


@dataclass(frozen=True, slots=True)
class MaterializationRepository:
    """Transaction boundary for exact materialization tuple replay."""

    database: Path

    def create(
        self,
        catalog_generation_id: int,
        attribute_snapshot_id: int,
        versions: tuple[str, str],
    ) -> int:
        """Create or replay only the exact catalog/attribute/version tuple."""
        with connect(self.database) as connection:
            catalog = query(
                connection,
                """
                SELECT five_source_ids_json FROM catalog_generations WHERE id = ?
                """,
                (catalog_generation_id,),
            ).fetchone()
            attribute = query(
                connection,
                """
                SELECT catalog_generation_id, status
                FROM attribute_snapshots WHERE id = ?
                """,
                (attribute_snapshot_id,),
            ).fetchone()
            if catalog is None or attribute != (catalog_generation_id, "complete"):
                raise RepositoryContractError(
                    detail="materialization source incomplete"
                )
            source_map = SOURCE_MAP_ADAPTER.validate_json(as_text(catalog[0]))
            source_ids = tuple(source_map[key] for key in sorted(source_map))
            digest = materialization_source_sha(
                catalog_generation_id,
                source_ids,
                attribute_snapshot_id,
            )
            _ = query(
                connection,
                """
                INSERT INTO materialization_snapshots(
                    catalog_generation_id, attribute_snapshot_id,
                    materialization_source_sha, normalization_version,
                    materialization_policy_version, status, attempt_no,
                    heartbeat_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'building', 1,
                          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                          strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(
                    materialization_source_sha, normalization_version,
                    materialization_policy_version
                ) DO NOTHING
                """,
                (
                    catalog_generation_id,
                    attribute_snapshot_id,
                    digest,
                    versions[0],
                    versions[1],
                ),
            )
            row = query(
                connection,
                """
                SELECT id, catalog_generation_id, attribute_snapshot_id
                FROM materialization_snapshots
                WHERE materialization_source_sha = ?
                  AND normalization_version = ?
                  AND materialization_policy_version = ?
                """,
                (digest, versions[0], versions[1]),
            ).fetchone()
            if row is None or row[1:] != (
                catalog_generation_id,
                attribute_snapshot_id,
            ):
                raise RepositoryContractError(
                    detail="materialization digest collision detected"
                )
            return as_int(row[0])
