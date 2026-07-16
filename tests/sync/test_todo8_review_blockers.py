from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.sync.paginator import PageMeta, PageSequence, SyncInvariantError
from g2b_compare.sync.publisher import (
    PublicationRequest,
    SourceDelta,
    publish_operation,
)
from tests.sync.todo8_fixture import NOW, add_page, database, record, release_bytes
from tests.sync.todo8_review_support import independent_states, seed_ready_release

if TYPE_CHECKING:
    from pathlib import Path


def test_incomplete_pagination_cannot_publish_or_swap_pointer(tmp_path: Path) -> None:
    db = database(tmp_path / "capability.sqlite3")
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    origin_page = add_page(db, operation.value, "row")
    incomplete = PageSequence.empty().add(PageMeta(1, 10, 20, 10))
    unscoped = PageSequence.empty().add(PageMeta(1, 10, 1, 1)).finalize()

    with pytest.raises(SyncInvariantError, match="missing-window-page"):
        _ = incomplete.finalize()
    with pytest.raises(SyncInvariantError, match="publication-not-validated"):
        _ = publish_operation(
            db.path,
            PublicationRequest(
                operation,
                "full",
                "2026-07-15",
                "2026-07-15",
                NOW,
                (SourceDelta(record("K-1", "P-1", origin_page, "a")),),
                (unscoped,),
            ),
        )
    with connect(db.path) as connection:
        pointer = query(
            connection,
            "SELECT COUNT(*) FROM active_source_snapshots",
        ).fetchone()
    assert pointer is not None
    assert as_int(pointer[0]) == 0


def test_kill_resume_matches_independent_uninterrupted_database(tmp_path: Path) -> None:
    uninterrupted, resumed = independent_states(tmp_path, mutate_resumed=False)

    assert uninterrupted == resumed


def test_release_freeze_includes_bundle_components_cache_and_source_manifest(
    tmp_path: Path,
) -> None:
    db = seed_ready_release(tmp_path / "release.sqlite3")

    frozen = release_bytes(db)

    assert b"bundle-sha" in frozen
    assert b"idx-art" in frozen
    assert b"relation-content" in frozen
    assert b"payload-sha" in frozen
    assert b"five_source_ids_json" in frozen
