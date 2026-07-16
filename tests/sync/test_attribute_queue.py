from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from g2b_compare.contracts.manifest import ContractManifest, DiscoverState
from g2b_compare.db.connection import connect
from g2b_compare.db.lifecycle import AttributeRepository
from g2b_compare.db.models import AttributeRecordInput
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.sync.attribute_queue import (
    AttributePlan,
    AttributeQueueStore,
    CatalogAttributeInput,
    CompleteFetch,
    FailedFetch,
    FetchCommit,
    PreviousAttribute,
    QueuePlanningInput,
    QuotaWindow,
    apply_fetch,
    dispatch_budget,
    plan_attribute_queue,
)
from tests.db.support import (
    NOW,
    add_catalog,
    add_complete_attribute,
    add_page,
    create_database,
)
from tests.sources.test_thing_list import attribute_manifest

if TYPE_CHECKING:
    from tests.db import support as db_support

NOW_DT = datetime(2026, 7, 16, tzinfo=UTC)
SQL = "SELECT attribute_source_key FROM attribute_records WHERE attribute_snapshot_id=?"


def _product(
    product_id: str, priority: int = 0, fingerprint: str = "f"
) -> CatalogAttributeInput:
    return CatalogAttributeInput(product_id, priority, fingerprint * 64)


def _previous(
    product_id: str,
    *,
    fingerprint: str = "f",
    complete: bool = True,
    age_days: int = 1,
) -> PreviousAttribute:
    return PreviousAttribute(
        product_id,
        fingerprint * 64,
        NOW_DT - timedelta(days=age_days),
        complete,
        7,
    )


def _plan(
    products: tuple[CatalogAttributeInput, ...],
    previous: tuple[PreviousAttribute, ...] = (),
) -> AttributePlan:
    return plan_attribute_queue(QueuePlanningInput(11, products, previous, NOW_DT))


def test_happy_queue_is_category_then_product_deterministic() -> None:
    plan = _plan((_product("B", 2), _product("C", 1), _product("A", 1)))
    assert tuple(item.product_id for item in plan.queued) == ("A", "C", "B")


def test_failure_quota_unverified() -> None:
    verified = attribute_manifest()
    unverified = ContractManifest(
        operation=verified.operation,
        quota=verified.quota,
        state=DiscoverState(attempt_ledger_ids=()),
    )
    with pytest.raises(ValueError, match="quota-unverified"):
        _ = dispatch_budget(QuotaWindow(unverified, 0, 0))


@pytest.mark.parametrize("consumed", [898, 899])
def test_failure_low_quota_zero_call(consumed: int) -> None:
    assert (
        dispatch_budget(
            QuotaWindow(attribute_manifest(), consumed, consumed)
        ).allowed_calls
        == 0
    )


def test_failure_probe_budget_below_three() -> None:
    assert (
        dispatch_budget(QuotaWindow(attribute_manifest(), 897, 899)).allowed_calls == 0
    )


def test_failure_rolling_ceiling() -> None:
    budget = dispatch_budget(QuotaWindow(attribute_manifest(), 900, 0))
    assert (budget.ceiling, budget.allowed_calls) == (900, 0)


def test_failure_provider_window_ceiling() -> None:
    budget = dispatch_budget(QuotaWindow(attribute_manifest(), 0, 900))
    assert budget.allowed_calls == 0


def test_exact_900_of_1001_are_dispatchable() -> None:
    plan = _plan(tuple(_product(f"P-{index:04d}") for index in range(1001)))
    budget = dispatch_budget(QuotaWindow(attribute_manifest(), 0, 0))
    assert len(plan.dispatchable(budget)) == 900


def test_failure_unchanged_product_not_requeued() -> None:
    plan = _plan((_product("P-1"),), (_previous("P-1"),))
    assert plan.queued == ()
    assert plan.carried_forward == ("P-1",)


def test_duplicate_product_is_enqueued_once() -> None:
    plan = _plan((_product("P-1"), _product("P-1")))
    assert len(plan.queued) == 1


def test_failure_changed_product_requeued() -> None:
    plan = _plan((_product("P-1", fingerprint="a"),), (_previous("P-1"),))
    assert plan.queued[0].reason == "changed"


def test_failure_ttl_product_requeued() -> None:
    plan = _plan((_product("P-1"),), (_previous("P-1", age_days=90),))
    assert plan.queued[0].reason == "ttl"


def test_failure_delivery_only_preserves_attributes() -> None:
    plan = _plan((_product("P-1"),), (_previous("P-1"),))
    assert plan.carried_forward == ("P-1",)


def test_never_complete_is_requeued() -> None:
    plan = _plan((_product("P-1"),), (_previous("P-1", complete=False),))
    assert plan.queued[0].reason == "never-complete"


def test_failure_catalog_generation_changed_inflight() -> None:
    commit = FetchCommit(1, 2, 99, "P-1", "f" * 64, CompleteFetch((), NOW))
    assert (
        apply_fetch(AttributeRepository(Path("unused.sqlite3")), commit) == "raw-only"
    )


def test_failure_kill_resume(tmp_path: Path) -> None:
    db = create_database(tmp_path)
    generation = add_catalog(db)
    store = AttributeQueueStore(db.path)
    plan = plan_attribute_queue(
        QueuePlanningInput(
            generation,
            (_product("B"), _product("A")),
            (),
            NOW_DT,
        )
    )
    store.seed(generation, plan.queued)
    resumed = AttributeQueueStore(db.path).ready(generation, NOW_DT, 10)
    assert tuple(item.product_id for item in resumed) == ("A", "B")


def _successor(
    tmp_path: Path,
) -> tuple[db_support.TestDatabase, int, int, AttributeRecordInput]:
    db = create_database(tmp_path)
    catalog = add_catalog(db)
    parent, _page = add_complete_attribute(db, catalog)
    successor = db.attribute.create_snapshot(catalog, parent, 1)
    db.attribute.carry_forward_product(parent, successor, "P-1")
    page_id, _receipt = add_page(db, "attributes", b'{"value":"4K"}')
    record = AttributeRecordInput("P-1", "A-new", page_id, '{"value":"4K"}', "b" * 64)
    return db, catalog, successor, record


def test_failure_deleted_attribute_persists(tmp_path: Path) -> None:
    db, catalog, successor, record = _successor(tmp_path)
    commit = FetchCommit(
        catalog, catalog, successor, "P-1", "f" * 64, CompleteFetch((record,), NOW)
    )
    assert apply_fetch(db.attribute, commit) == "applied"
    with connect(db.path) as connection:
        rows = query(
            connection,
            SQL,
            (successor,),
        ).fetchall()
    assert tuple(as_text(row[0]) for row in rows) == ("A-new",)


def test_failure_partial_pagination_replaces_old(tmp_path: Path) -> None:
    db, catalog, successor, _record = _successor(tmp_path)
    commit = FetchCommit(
        catalog, catalog, successor, "P-1", "f" * 64, FailedFetch("partial-pagination")
    )
    assert apply_fetch(db.attribute, commit) == "retained"
    with connect(db.path) as connection:
        row = query(
            connection,
            "SELECT COUNT(*) FROM attribute_records WHERE attribute_snapshot_id = ?",
            (successor,),
        ).fetchone()
    assert row is not None
    assert as_int(row[0]) == 1


def test_complete_empty_atomically_deletes_old(tmp_path: Path) -> None:
    db, catalog, successor, _record = _successor(tmp_path)
    commit = FetchCommit(
        catalog,
        catalog,
        successor,
        "P-1",
        "f" * 64,
        CompleteFetch((), NOW, official_no_data=True),
    )
    assert apply_fetch(db.attribute, commit) == "applied"
    with connect(db.path) as connection:
        row = query(
            connection,
            "SELECT COUNT(*) FROM attribute_records WHERE attribute_snapshot_id = ?",
            (successor,),
        ).fetchone()
    assert row is not None
    assert as_int(row[0]) == 0
