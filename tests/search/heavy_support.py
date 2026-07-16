from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from g2b_compare.search.index_builder import IndexBuildRequest, build_index
from g2b_compare.search.index_store import IndexStore
from g2b_compare.search.query import SearchPurityError
from g2b_compare.sync.release_guard import frozen_active_release
from tests.db.support import create_database
from tests.db.test_invariant_repairs import create_ready_bundle

from .support import corpus


@dataclass(frozen=True, slots=True)
class HeavyReceipt:
    members: int
    exact_ids: tuple[str, ...]
    success_preserved: bool
    failure_preserved: bool
    query_paths_pure: bool


def run_heavy_evidence() -> HeavyReceipt:
    with TemporaryDirectory() as directory:
        test_db = create_database(Path(directory))
        _materialization_id, active_bundle_id = create_ready_bundle(
            test_db,
            ("complete", "complete", "complete"),
        )
        with closing(sqlite3.connect(test_db.path)) as connection:
            _ = connection.execute(
                "INSERT INTO active_release VALUES (1, ?)",
                (active_bundle_id,),
            )
            connection.commit()
        before = frozen_active_release(test_db.path)
        request = IndexBuildRequest(17, "v1", "v1", "v1", corpus())
        bundle = build_index(request)
        store = IndexStore.create(test_db.path)
        store.publish(request, bundle)
        after_success = frozen_active_release(test_db.path)
        failure_observed = False
        try:
            store.publish(request, bundle)
        except sqlite3.IntegrityError:
            failure_observed = True
        after_failure = frozen_active_release(test_db.path)
        query_paths_pure = query_paths_are_pure(store)
        groups = store.resolve_exact("영상감시장치", ("4410", "441015"))
        exact_ids = tuple(item.product_id for item in groups[0].products)
        store.close()
    return HeavyReceipt(
        len(bundle.members),
        exact_ids,
        before == after_success,
        failure_observed and before == after_failure,
        query_paths_pure,
    )


def query_paths_are_pure(store: IndexStore) -> bool:
    store.enforce_query_only()
    before = store.total_changes
    with (
        patch("socket.create_connection", side_effect=AssertionError) as socket_guard,
        patch(
            "http.client.HTTPConnection.connect",
            side_effect=AssertionError,
        ) as http_guard,
    ):
        exact = store.resolve_exact("영상감시장치", ("4410", "441015"))
        recalled = store.recall("감시")
        scored = store.score("800만화소 실외형")
    return (
        store.query_only_enabled
        and before == 0
        and store.total_changes == 0
        and socket_guard.call_count == 0
        and http_guard.call_count == 0
        and bool(exact)
        and bool(recalled)
        and bool(scored)
    )


def purity_contract_failure(reason: str) -> None:
    with TemporaryDirectory() as directory:
        store = IndexStore.create(Path(directory) / "purity.sqlite3")
        request = IndexBuildRequest(17, "v1", "v1", "v1", corpus())
        store.publish(request, build_index(request))
        try:
            pure = query_paths_are_pure(store)
        finally:
            store.close()
    if not pure:
        raise AssertionError(reason)
    raise SearchPurityError(reason)
