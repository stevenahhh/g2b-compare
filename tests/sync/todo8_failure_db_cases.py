from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Final, Literal, assert_never

from pydantic import TypeAdapter

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.sync.catalog import advance_catalog, product_is_active
from g2b_compare.sync.publisher import (
    PublicationRequest,
    SourceDelta,
    active_records,
    active_source_digest,
    publish_operation,
)
from tests.sync.todo8_fixture import (
    NOW,
    add_page,
    complete_products,
    database,
    publish,
    record,
    release_bytes,
    setup_five_sources,
    validated_pages,
)

if TYPE_CHECKING:
    from pathlib import Path

type DatabaseScenario = Literal[
    "unchanged-row-lost",
    "absence-delta",
    "absence-full",
    "explicit-cancel",
    "registration-key-mismatch",
    "one-source-cancel",
    "kill-staging",
    "delivery-change-requeues-all",
    "changed-product-not-requeued",
    "release-pointer-changed",
    "materialization-created-by-sync",
]
DATABASE_ADAPTER: Final[TypeAdapter[DatabaseScenario]] = TypeAdapter[DatabaseScenario](
    DatabaseScenario
)


def observe_database_case(scenario: str, path: Path) -> str:
    return _observe_database(DATABASE_ADAPTER.validate_python(scenario), path)


def _observe_database(scenario: DatabaseScenario, path: Path) -> str:
    match scenario:
        case "unchanged-row-lost" | "absence-delta" | "absence-full":
            return _absence_observation(path, scenario)
        case "explicit-cancel" | "registration-key-mismatch":
            return _cancel_observation(path, scenario)
        case "one-source-cancel":
            return _one_source_cancel(path)
        case "kill-staging":
            return _kill_observation(path)
        case "delivery-change-requeues-all" | "changed-product-not-requeued":
            return _catalog_observation(path, scenario)
        case "release-pointer-changed" | "materialization-created-by-sync":
            return _forbidden_surface_observation(path, scenario)
        case _:
            assert_never(scenario)


def _absence_observation(path: Path, scenario: str) -> str:
    db = database(path)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    page = add_page(db, operation.value, "base")
    _ = publish(
        db,
        operation,
        "full",
        (
            SourceDelta(record("K-1", "P-1", page, "a")),
            SourceDelta(record("K-2", "P-2", page, "b")),
        ),
    )
    mode: Literal["full", "delta"] = "full" if scenario == "absence-full" else "delta"
    _ = publish(
        db,
        operation,
        mode,
        (SourceDelta(record("K-2", "P-2", page, "c")),),
    )
    rows = active_records(path, operation)
    tombstones = sum(row.is_tombstone for row in rows)
    if scenario == "unchanged-row-lost":
        assert any(row.key == "K-1" and not row.is_tombstone for row in rows)
        return "unchanged-row-preserved"
    return f"{mode}-absence-tombstones={tombstones}"


def _cancel_observation(path: Path, scenario: str) -> str:
    db = database(path)
    operation = Operation.GET_SHOPPING_MALL_PRODUCT_INFO
    page = add_page(db, operation.value, "cancel")
    _ = publish(db, operation, "full", (SourceDelta(record("K-1", "P-1", page, "a")),))
    product_id = "P-2" if scenario == "registration-key-mismatch" else "P-1"
    _ = publish(
        db,
        operation,
        "delta",
        (
            SourceDelta(
                record("K-1", product_id, page, "b"),
                explicit_cancel=True,
            ),
        ),
    )
    count = sum(row.is_tombstone for row in active_records(path, operation))
    return f"explicit-cancel-tombstone={count}"


def _one_source_cancel(path: Path) -> str:
    db = database(path)
    for operation in tuple(Operation)[:2]:
        page = add_page(db, operation.value, operation.value)
        _ = publish(
            db,
            operation,
            "full",
            (SourceDelta(record("K", "P-1", page, "a")),),
        )
    first = next(iter(Operation))
    page = add_page(db, first.value, "cancel")
    _ = publish(
        db,
        first,
        "delta",
        (SourceDelta(record("K", "P-1", page, "b"), explicit_cancel=True),),
    )
    return f"product-active-from-other-offer={int(product_is_active(path, 'P-1'))}"


def _kill_observation(path: Path) -> str:
    db = database(path)
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    page = add_page(db, operation.value, "base")
    _ = publish(db, operation, "full", (SourceDelta(record("K", "P", page, "a")),))
    before = active_source_digest(path)
    kill_message = "intentional-kill"

    def kill(snapshot_id: int) -> None:
        _ = snapshot_id
        raise RuntimeError(kill_message)

    with suppress(RuntimeError):
        _ = publish_operation(
            path,
            PublicationRequest(
                operation,
                "delta",
                "2026-07-15",
                "2026-07-15",
                NOW,
                (),
                validated_pages(
                    operation,
                    "2026-07-15",
                    "2026-07-15",
                    0,
                ),
            ),
            kill,
        )
    assert active_source_digest(path) == before
    return "active-source-unchanged"


def _catalog_observation(path: Path, scenario: str) -> str:
    db = database(path)
    setup_five_sources(db)
    first = advance_catalog(path, NOW)
    _ = complete_products(db, first, ("P-1",))
    operation = (
        Operation.GET_DELIVERY_REQUEST_DETAIL
        if scenario == "delivery-change-requeues-all"
        else Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    )
    page = add_page(db, operation.value, "changed")
    key = "D-1" if operation is Operation.GET_DELIVERY_REQUEST_DETAIL else "K-1"
    _ = publish(
        db,
        operation,
        "delta",
        (SourceDelta(record(key, "P-1", page, "e")),),
    )
    advance = advance_catalog(path, NOW)
    if scenario == "delivery-change-requeues-all":
        return f"delivery-change-requeued={len(advance.queued_products)}"
    return f"changed-product-requeued={','.join(advance.queued_products)}"


def _forbidden_surface_observation(path: Path, scenario: str) -> str:
    db = database(path)
    before_release = release_bytes(db)
    setup_five_sources(db)
    _ = advance_catalog(path, NOW)
    if scenario == "release-pointer-changed":
        assert release_bytes(db) == before_release
        return "active-release-unchanged"
    with connect(path) as connection:
        row = query(
            connection,
            "SELECT COUNT(*) FROM materialization_snapshots",
        ).fetchone()
    assert row is not None
    return f"materializations-created={as_int(row[0])}"
