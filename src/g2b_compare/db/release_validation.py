"""Read and hash immutable release component and cache graphs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from g2b_compare.ranking.cache import (
    CacheContractError,
    CachePayload,
    CacheRow,
    cache_content_sha,
    canonical_payload,
    require_payload_schema,
)

from .hashes import canonical_json
from .sql import as_int, as_text, query

if TYPE_CHECKING:
    from sqlite3 import Connection

MATERIALIZATION_INCOMPLETE: Final = "materialization-incomplete"
INDEX_INCOMPLETE: Final = "index-incomplete"
RELATION_INCOMPLETE: Final = "relation-incomplete"
CACHE_CARDINALITY: Final = "cache-cardinality"
CACHE_PAYLOAD_CORRUPTION: Final = "cache-payload-corruption"


@dataclass(frozen=True, slots=True)
class ReleaseComponents:
    """Exact component digests captured before cache precomputation."""

    materialization_source_sha: str
    normalization_version: str
    materialization_policy_version: str
    index_artifact_sha: str
    index_manifest_sha: str
    relation_source_manifest_sha: str
    relation_content_sha: str
    data_as_of: str


@dataclass(frozen=True, slots=True)
class ReleaseHashInput:
    """Semantic release identity inputs independent of SQLite row IDs."""

    components: ReleaseComponents
    ranking_version: str
    expected_cache_rows: int
    cache_content_sha: str


def load_components(
    connection: Connection,
    materialization_id: int,
    index_version_id: int,
    relation_snapshot_id: int,
) -> ReleaseComponents:
    """Load a complete and mutually owned component graph."""
    material = query(
        connection,
        """SELECT m.status,m.catalog_generation_id,m.materialization_source_sha,
                  m.normalization_version,m.materialization_policy_version,
                  a.status,a.catalog_generation_id
           FROM materialization_snapshots m
           JOIN attribute_snapshots a ON a.id=m.attribute_snapshot_id
           WHERE m.id=?""",
        (materialization_id,),
    ).fetchone()
    material_valid = (
        material is not None
        and material[0] == "complete"
        and material[5] == "complete"
        and material[1] == material[6]
    )
    if not material_valid or material is None:
        raise ValueError(MATERIALIZATION_INCOMPLETE)
    index = query(
        connection,
        """SELECT materialization_id,index_artifact_sha,index_manifest_sha,status
           FROM index_versions WHERE id=?""",
        (index_version_id,),
    ).fetchone()
    if index is None or index[0] != materialization_id or index[3] != "complete":
        raise ValueError(INDEX_INCOMPLETE)
    relation = query(
        connection,
        """SELECT source_manifest_sha,relation_content_sha,status
           FROM relation_snapshots WHERE id=?""",
        (relation_snapshot_id,),
    ).fetchone()
    if relation is None or relation[2] != "complete":
        raise ValueError(RELATION_INCOMPLETE)
    data = query(
        connection,
        """SELECT COALESCE(MAX(data_as_of),'') FROM products
           WHERE materialization_id=? AND active=1""",
        (materialization_id,),
    ).fetchone()
    if data is None:
        raise ValueError(MATERIALIZATION_INCOMPLETE)
    return ReleaseComponents(
        as_text(material[2]),
        as_text(material[3]),
        as_text(material[4]),
        as_text(index[1]),
        as_text(index[2]),
        as_text(relation[0]),
        as_text(relation[1]),
        as_text(data[0]),
    )


def active_anchors(connection: Connection, materialization_id: int) -> tuple[str, ...]:
    """Return all active product IDs in UTF-8-compatible binary order."""
    rows = query(
        connection,
        """SELECT product_id FROM products
           WHERE materialization_id=? AND active=1
           ORDER BY product_id COLLATE BINARY""",
        (materialization_id,),
    ).fetchall()
    return tuple(as_text(row[0]) for row in rows)


def validate_cache(
    connection: Connection,
    materialization_id: int,
    bundle_id: int,
    attempt_no: int,
) -> tuple[str, int]:
    """Validate exact current-attempt cardinality and canonical row content."""
    anchors = active_anchors(connection, materialization_id)
    rows = query(
        connection,
        """SELECT anchor_id,slot,payload_json,payload_sha FROM comparator_cache
           WHERE release_bundle_id=? AND attempt_no=?
           ORDER BY anchor_id COLLATE BINARY,slot""",
        (bundle_id, attempt_no),
    ).fetchall()
    expected = tuple((anchor, slot) for anchor in anchors for slot in range(1, 4))
    observed = tuple((as_text(row[0]), as_int(row[1])) for row in rows)
    if observed != expected:
        raise ValueError(CACHE_CARDINALITY)
    cache_rows: list[CacheRow] = []
    for row in rows:
        try:
            payload = CachePayload.model_validate_json(as_text(row[2]))
            document, digest = canonical_payload(payload)
        except (ValidationError, CacheContractError) as error:
            raise ValueError(CACHE_PAYLOAD_CORRUPTION) from error
        try:
            require_payload_schema(payload)
        except CacheContractError as error:
            raise ValueError(error.code) from error
        if document != as_text(row[2]) or digest != as_text(row[3]):
            raise ValueError(CACHE_PAYLOAD_CORRUPTION)
        cache_rows.append(CacheRow(as_text(row[0]), as_int(row[1]), payload))
    return cache_content_sha(tuple(cache_rows)), len(rows)


def release_bundle_sha(identity: ReleaseHashInput) -> str:
    """Hash the exact immutable release components and current cache attempt."""
    component = identity.components
    document = canonical_json(
        {
            "cache_content_sha": identity.cache_content_sha,
            "cache_payload_schema_version": "1",
            "expected_cache_rows": identity.expected_cache_rows,
            "index_artifact_sha": component.index_artifact_sha,
            "index_manifest_sha": component.index_manifest_sha,
            "materialization_policy_version": (
                component.materialization_policy_version
            ),
            "materialization_source_sha": component.materialization_source_sha,
            "normalization_version": component.normalization_version,
            "ranking_version": identity.ranking_version,
            "relation_content_sha": component.relation_content_sha,
            "source_manifest_sha": component.relation_source_manifest_sha,
        }
    )
    return hashlib.sha256(document.encode()).hexdigest()
