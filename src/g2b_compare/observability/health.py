"""Fail-closed process, database, index, and release readiness probes."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from g2b_compare.contracts.live_output import LiveObservedDocument
from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.release import ReleaseStore
from g2b_compare.db.release_types import (
    BundleRecord,
    BundleStatus,
    ReleaseKey,
    ReleaseStoreError,
)
from g2b_compare.observability.data_status import data_statuses

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonValue

CONTRACT_PATH: Final = Path("docs/api-contract-observed.json")
DEFAULT_INDEX_PATH: Final = Path("search-index.bin")


@dataclass(frozen=True, slots=True)
class Probe:
    """HTTP-ready probe result."""

    ok: bool
    status: str
    detail: dict[str, JsonValue]


def health(
    database: Path,
    index_path: Path = DEFAULT_INDEX_PATH,
) -> Probe:
    """Report process liveness while distinguishing corrupt dependencies."""
    detail: dict[str, JsonValue] = {
        "process": "ok",
        "database": "missing",
        "index": "unknown",
    }
    if not database.is_file():
        return Probe(ok=False, status="empty", detail=detail)
    try:
        with connect_read_only(database) as connection:
            check = cast(
                "tuple[object, ...] | None",
                connection.execute("PRAGMA quick_check").fetchone(),
            )
            detail["database"] = "ok" if check == ("ok",) else "corrupt"
    except sqlite3.DatabaseError:
        detail["database"] = "corrupt"
        return Probe(ok=False, status="corrupt-db", detail=detail)
    if check != ("ok",):
        return Probe(ok=False, status="corrupt-db", detail=detail)
    if not index_path.is_file() or index_path.stat().st_size == 0:
        detail["index"] = "missing"
        return Probe(ok=False, status="corrupt-index", detail=detail)
    detail["index"] = "ok"
    return Probe(ok=True, status="current", detail=detail)


def readiness(
    database: Path,
    *,
    root: Path | None = None,
    index_path: Path = DEFAULT_INDEX_PATH,
    contract_path: Path | None = None,
) -> Probe:
    """Validate the exact pinned release without considering newer attempts."""
    live = health(database, index_path)
    if not live.ok:
        return live
    try:
        record, key, expected_index, attributes_complete = _active_release(database)
        ReleaseStore(database).verify_ready(key, record)
        if _sha256(index_path) != expected_index:
            return Probe(
                ok=False,
                status="corrupt-index",
                detail={"index": "sha-mismatch"},
            )
        base = root or Path()
        live_contract = _verified_contract(base / (contract_path or CONTRACT_PATH))
    except (ReleaseStoreError, ValueError, sqlite3.DatabaseError, OSError) as error:
        return Probe(ok=False, status="not-ready", detail={"reason": str(error)})
    if not attributes_complete:
        return Probe(ok=False, status="partial-attribute", detail={"index": "ok"})
    if not live_contract:
        return Probe(ok=False, status="live-gate", detail={"operations": 0})
    return Probe(
        ok=True,
        status="ready",
        detail={
            "bundle_id": record.bundle_id,
            "operations": len(Operation),
            "data_statuses": list(data_statuses(database)),
        },
    )


def _active_release(database: Path) -> tuple[BundleRecord, ReleaseKey, str, bool]:
    with connect_read_only(database) as connection:
        row = cast(
            "tuple[object, ...] | None",
            connection.execute(
                """SELECT b.id,b.status,b.attempt_no,b.expected_cache_rows,
                          b.written_cache_rows,b.cache_content_sha,
                          b.release_bundle_sha,b.ready_attempt_no,
                          b.materialization_id,b.index_version_id,
                          b.relation_snapshot_id,b.ranking_version,
                          i.index_artifact_sha,
                          ats.complete_product_count,ats.active_product_count
                   FROM active_release a JOIN release_bundles b
                     ON b.id=a.bundle_id
                   JOIN index_versions i ON i.id=b.index_version_id
                   JOIN materialization_snapshots ms
                     ON ms.id=b.materialization_id
                   JOIN attribute_snapshots ats
                     ON ats.id=ms.attribute_snapshot_id
                   WHERE a.singleton=1"""
            ).fetchone(),
        )
    if row is None:
        reason = "no-active-release"
        raise ValueError(reason)
    record = BundleRecord(
        bundle_id=int(cast("int", row[0])),
        status=BundleStatus(str(row[1])),
        attempt_no=int(cast("int", row[2])),
        expected_rows=int(cast("int", row[3])),
        written_rows=int(cast("int", row[4])),
        cache_sha=str(row[5]) if row[5] else None,
        bundle_sha=str(row[6]) if row[6] else None,
        ready_attempt_no=int(cast("int", row[7])) if row[7] is not None else None,
        owned=False,
    )
    key = ReleaseKey(
        int(cast("int", row[8])),
        int(cast("int", row[9])),
        int(cast("int", row[10])),
        str(row[11]),
    )
    return (
        record,
        key,
        str(row[12]),
        int(cast("int", row[13])) == int(cast("int", row[14])),
    )


def _verified_contract(path: Path) -> bool:
    document = LiveObservedDocument.model_validate_json(path.read_bytes())
    operations = {item.operation for item in document.manifests}
    return (
        len(document.manifests) == len(Operation)
        and operations == set(Operation)
        and all(item.manifest.state.phase == "VERIFIED" for item in document.manifests)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
