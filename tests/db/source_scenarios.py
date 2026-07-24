from __future__ import annotations

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from g2b_compare.db.connection import connect
from g2b_compare.db.hashes import (
    canonical_record_sha,
    catalog_source_identity,
    request_identity,
)
from g2b_compare.db.migrate import MIGRATION_DIRECTORY, MigrationDriftError, migrate
from g2b_compare.db.models import (
    CanonicalSourceRecord,
    QuotaReservationInput,
    RequestInput,
    SourceRecordInput,
    SourceSnapshotInput,
    SyncPageInput,
    SyncRunInput,
    SyncWindowInput,
)
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_int, query

from .support import (
    NOW,
    OPS,
    add_catalog,
    add_complete_attribute,
    add_page,
    create_database,
)

if TYPE_CHECKING:
    from pathlib import Path


def source_record(page_id: int, key: str = "R-1") -> SourceRecordInput:
    return SourceRecordInput(
        source_record_key=key,
        product_id="P-1",
        origin_page_id=page_id,
        raw_fields_json="{}",
        payload_sha="a" * 64,
        canonical_record_sha="b" * 64,
    )


def snapshot_input(operation: str, parent_id: int | None = None) -> SourceSnapshotInput:
    return SourceSnapshotInput(
        operation=operation,
        parent_id=parent_id,
        mode="full",
        window_start="2026-07-01",
        window_end="2026-07-14",
        completeness="complete",
    )


def canonical_record(detail: str = "800만화소") -> CanonicalSourceRecord:
    return CanonicalSourceRecord(
        operation="contract-a",
        stable_source_key="R-1",
        product_id="P-1",
        category="C",
        detail_category="D",
        product_name="영상감시장치",
        spec_name="카메라",
        detail=detail,
        characteristic="실외형",
        active=True,
        unit_basis="대",
    )


def scenario_kill_before_pointer(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    page_id, _receipt = add_page(db, "contract-a", b"old")
    old_id = db.source.create_source_snapshot(snapshot_input("contract-a"))
    db.source.add_source_record(old_id, "contract-a", source_record(page_id, "old"))
    db.source.publish_source_snapshot(old_id, NOW)
    new_id = db.source.create_source_snapshot(snapshot_input("contract-a", old_id))
    db.source.add_source_record(new_id, "contract-a", source_record(page_id, "new"))
    assert db.source.active_source_record_keys("contract-a") == ("old",)


def scenario_fk(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    snapshot_id = db.source.create_source_snapshot(snapshot_input("contract-a"))
    with pytest.raises(sqlite3.IntegrityError):
        db.source.add_source_record(snapshot_id, "contract-a", source_record(999))


def scenario_duplicate_source_key(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    page_id, _receipt = add_page(db, "contract-a", b"row")
    snapshot_id = db.source.create_source_snapshot(snapshot_input("contract-a"))
    db.source.add_source_record(snapshot_id, "contract-a", source_record(page_id))
    with pytest.raises(sqlite3.IntegrityError):
        db.source.add_source_record(snapshot_id, "contract-a", source_record(page_id))


def scenario_canonical_media_equivalence(tmp_path: Path) -> None:
    _db = create_database(tmp_path)
    parsed_json = canonical_record()
    parsed_xml = canonical_record()
    assert canonical_record_sha(parsed_json) == canonical_record_sha(parsed_xml)


def scenario_canonical_key_order(tmp_path: Path) -> None:
    _db = create_database(tmp_path)
    forward = tuple((operation, index) for index, operation in enumerate(OPS, 1))
    assert catalog_source_identity(forward) == catalog_source_identity(forward[::-1])


def scenario_cross_operation_offer_key(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    catalog_id = add_catalog(db)
    attribute_id, _page_id = add_complete_attribute(db, catalog_id)
    materialization_id = db.materialization.create(
        catalog_id, attribute_id, ("n1", "p1")
    )
    with connect(db.path) as connection:
        _ = query(
            connection,
            """
            INSERT INTO products(
                materialization_id,product_id,category_no,detail_category_no,
                product_name_raw,product_name_key,active,data_as_of
            ) VALUES (?, 'P-1', 'C', 'D', 'name', 'name', 1, ?)
            """,
            (materialization_id, NOW),
        )
        for operation in ("contract-a", "contract-b"):
            _ = query(
                connection,
                """
                INSERT INTO catalog_offers(
                    materialization_id,operation,offer_key,product_id,
                    contract_price_won,unit_raw,unit_key,active,source_updated_at
                ) VALUES (
                    ?, ?, 'same-key', 'P-1', 1000, '대', '대', 1, ?
                )
                """,
                (materialization_id, operation, NOW),
            )
        count = query(connection, "SELECT COUNT(*) FROM catalog_offers").fetchone()
    assert count is not None
    assert as_int(count[0]) == 2


def scenario_request_fingerprint_collision(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    request = RequestInput("op", "GET", "/path", (("pageNo", "1"),), NOW)
    _params_json, _params_sha, fingerprint = request_identity(request)
    with connect(db.path) as connection:
        _ = query(
            connection,
            """
            INSERT INTO request_manifests VALUES (
                NULL, 'other', 'GET', '/other', '{}', 'sha', ?, ?
            )
            """,
            (fingerprint, NOW),
        )
    with pytest.raises(RepositoryContractError, match="collision"):
        _ = db.ingest.register_request(request)


def scenario_duplicate_window_page(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    receipt = db.raw.put(b"same", "application/json")
    db.ingest.register_raw_blob(receipt, NOW)
    run_id = db.ingest.create_run(SyncRunInput("op", "full", NOW))
    request_id = db.ingest.register_request(
        RequestInput("op", "GET", "/op", (("pageNo", "1"),), NOW)
    )
    for ordinal in (0, 1):
        window_id = db.ingest.create_window(
            SyncWindowInput(run_id, ordinal, "2026-07-01", "2026-07-14")
        )
        _ = db.ingest.create_page(
            SyncPageInput(
                run_id,
                window_id,
                1,
                request_id,
                receipt.body_sha,
                1,
                1,
                200,
                "application/json",
            )
        )


def scenario_cross_operation_request_sha(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    request_a = RequestInput("a", "GET", "/items", (("pageNo", "1"),), NOW)
    request_b = RequestInput("b", "GET", "/items", (("pageNo", "1"),), NOW)
    assert db.ingest.register_request(request_a) != db.ingest.register_request(
        request_b
    )


def scenario_quota_concurrent_ceiling(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    quota = QuotaReservationInput("op", NOW, "2026-07-13T00:00:00Z", "20260714", 3)

    def reserve() -> bool:
        try:
            _ = db.ingest.reserve_quota(quota)
        except RepositoryContractError:
            return False
        return True

    def reserve_for_index(_index: int) -> bool:
        return reserve()

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = tuple(executor.map(reserve_for_index, range(5)))
    assert results.count(True) == 3


def scenario_quota_crash_after_reserve(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    quota = QuotaReservationInput("op", NOW, "2026-07-13T00:00:00Z", "20260714", 1)
    _ = db.ingest.reserve_quota(quota)
    with pytest.raises(RepositoryContractError, match="exhausted"):
        _ = db.ingest.reserve_quota(quota)


def scenario_quota_retry_reservation(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    quota = QuotaReservationInput("op", NOW, "2026-07-13T00:00:00Z", "20260714", 2)
    first = db.ingest.reserve_quota(quota)
    db.ingest.finish_quota(first, 503, success=False)
    assert db.ingest.reserve_quota(quota) != first


def scenario_db_lock(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    with (
        closing(sqlite3.connect(db.path, isolation_level=None)) as first,
        closing(
            sqlite3.connect(db.path, timeout=0.001, isolation_level=None)
        ) as second,
    ):
        _ = first.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _ = second.execute("BEGIN IMMEDIATE")
        _ = first.execute("ROLLBACK")


def scenario_bad_migration(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    target = migrations / "0001_initial.sql"
    _ = shutil.copy2(MIGRATION_DIRECTORY / target.name, target)
    database = tmp_path / "migration.sqlite3"
    migrate(database, migrations)
    _ = target.write_text(
        target.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MigrationDriftError):
        migrate(database, migrations)


def scenario_missing_origin_page(tmp_path: Path) -> None:
    scenario_fk(tmp_path)
