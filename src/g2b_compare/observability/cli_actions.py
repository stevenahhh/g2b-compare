"""Command implementations for the thin installed CLI boundary."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from g2b_compare.contracts.live import LiveCaptureConfig, run_live_capture
from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.db.prune import RawRetentionRepository
from g2b_compare.db.repository import RepositoryContractError
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.observability.health import readiness
from g2b_compare.observability.logging import configure_logging, operation_log
from g2b_compare.observability.runtime_attributes import (
    attribute_pending_count,
    run_attribute_sync,
)
from g2b_compare.observability.runtime_materialize import materialize
from g2b_compare.observability.runtime_ops import (
    import_relations,
    precompute,
    rebuild_index,
)
from g2b_compare.observability.runtime_sync import run_catalog_sync
from g2b_compare.observability.secrets import verify_secrets
from g2b_compare.observability.server import serve_loopback

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonValue
    from g2b_compare.observability.cli_args import Args, RuntimePaths


def dispatch(args: Args, runtime: RuntimePaths) -> int:
    """Dispatch one already parsed command."""
    command = args.command
    if command in {"init-db", "capture-contract", "sync"}:
        return _dispatch_primary(command, args, runtime)
    if command in {"import-relations", "materialize", "rebuild-index", "precompute"}:
        return _dispatch_build(command, runtime)
    return _dispatch_operational(command, args, runtime)


def _dispatch_primary(command: str, args: Args, runtime: RuntimePaths) -> int:
    if command == "init-db":
        runtime.home.mkdir(parents=True, exist_ok=True)
        migrate(runtime.database)
        return emit({"status": "initialized"})
    if command == "capture-contract":
        return _capture_contract(runtime)
    return _sync(args, runtime)


def _dispatch_build(command: str, runtime: RuntimePaths) -> int:
    if command == "import-relations":
        return _import_relations(runtime)
    if command == "materialize":
        materialization_id = materialize(runtime.database)
        operation_log(configure_logging(), operation=command, status="ok")
        return emit(
            {"status": "materialized", "materialization_id": materialization_id}
        )
    if command == "rebuild-index":
        digest = rebuild_index(runtime.database, runtime.index)
        operation_log(configure_logging(), operation=command, status="ok")
        return emit({"status": "indexed", "sha256": digest})
    result = precompute(runtime.database)
    operation_log(configure_logging(), operation=command, status="ok")
    return emit(
        {
            "status": result.disposition.value,
            "bundle_id": result.bundle_id,
            "attempt": result.attempt_no,
        }
    )


def _dispatch_operational(
    command: str,
    args: Args,
    runtime: RuntimePaths,
) -> int:
    if command == "verify":
        probe = readiness(
            runtime.database,
            root=runtime.home,
            index_path=runtime.index,
            contract_path=runtime.contract,
        )
        return emit(
            {"ok": probe.ok, "status": probe.status, **probe.detail},
            not probe.ok,
        )
    if command == "coverage-stats":
        with connect(runtime.database) as connection:
            rows = query(
                connection,
                """SELECT category_no,detail_category_no,product_count,
                          numeric_span_count,parsed_semantic_count,
                          attribute_covered_count
                   FROM category_parse_stats
                   WHERE materialization_id=(
                     SELECT MAX(id) FROM materialization_snapshots
                     WHERE status='complete'
                   )
                   ORDER BY category_no,detail_category_no""",
            ).fetchall()
        return emit(
            {
                "status": "ok",
                "categories": [
                    {
                        "category_no": as_text(row[0]),
                        "detail_category_no": as_text(row[1]),
                        "product_count": as_int(row[2]),
                        "numeric_span_count": as_int(row[3]),
                        "parsed_semantic_count": as_int(row[4]),
                        "attribute_covered_count": as_int(row[5]),
                    }
                    for row in rows
                ],
            }
        )
    if command == "verify-secrets":
        leaks = verify_secrets(
            Path.cwd(),
            secret=os.getenv("G2B_SERVICE_KEY"),
            runtime_root=runtime.home,
            all_storage=args.all_storage,
        )
        return (
            error(f"secret-leak:{len(leaks)}", 1)
            if leaks
            else emit({"status": "clean"})
        )
    if command == "prune-raw":
        removed = RawRetentionRepository(runtime.database).prune_unreferenced(
            args.before
        )
        return emit({"status": "pruned", "count": len(removed)})
    if command == "serve":
        status, code = serve_loopback(
            runtime.database,
            runtime.index,
            runtime.contract,
            args.host,
            args.port,
        )
        return status if code is None else error(code, status)
    return error(f"{command}-requires-configured-input", 2)


def _capture_contract(runtime: RuntimePaths) -> int:
    secret_source = os.getenv("G2B_SECRET_SOURCE")
    if not secret_source:
        return error("missing-secret-source", 2)
    result = run_live_capture(
        LiveCaptureConfig(
            output_root=runtime.home,
            ledger_path=runtime.home / "contract-capture.sqlite3",
            quota_path=Path("docs/account-quota-observed.json").resolve(),
            secret_source=Path(secret_source).resolve(),
            observed_at=datetime.now(UTC),
        )
    )
    operation_log(
        configure_logging(),
        operation="capture-contract",
        status="ok" if result.success else "blocked",
    )
    return emit(
        {"status": "verified" if result.success else "blocked"},
        not result.success,
    )


def _import_relations(runtime: RuntimePaths) -> int:
    workbook = os.getenv("G2B_RELATIONS_WORKBOOK")
    relations, quarantined = import_relations(
        runtime.database,
        None if not workbook else Path(workbook).resolve(),
    )
    operation_log(configure_logging(), operation="import-relations", status="ok")
    return emit(
        {
            "status": "imported",
            "relations": relations,
            "quarantined": quarantined,
        }
    )


def _sync(args: Args, runtime: RuntimePaths) -> int:
    service_key = os.environ["G2B_SERVICE_KEY"]
    if args.mode == "attributes":
        applied, failure = _drain_attributes(args.max_batches, runtime, service_key)
        if failure is not None:
            return failure
        return emit({"status": "synced", "mode": args.mode, "applied": applied})
    mode = "full" if args.mode == "full" else "delta"
    try:
        results = run_catalog_sync(
            runtime.database,
            runtime.contract,
            service_key,
            mode,
        )
    except RepositoryContractError as caught:
        if caught.operation is None or caught.resume_not_before is None:
            raise
        return error(
            "quota-ceiling-exhausted",
            2,
            {
                "operation": caught.operation,
                "resume_not_before": caught.resume_not_before,
            },
        )
    operation_log(
        configure_logging(),
        operation="sync",
        status="ok",
        context={"run": sum(result.run_id for result in results)},
    )
    return emit(
        {
            "status": "synced",
            "mode": args.mode,
            "runs": len(results),
            "pages": sum(result.pages for result in results),
        }
    )


def _drain_attributes(
    max_batches: int,
    runtime: RuntimePaths,
    service_key: str,
) -> tuple[int, int | None]:
    if max_batches < 1:
        return 0, error("attribute-batch-bound-invalid", 2)
    applied = 0
    for batch in range(1, max_batches + 1):
        count = run_attribute_sync(
            runtime.database,
            runtime.contract,
            runtime.home / "raw",
            service_key,
        )
        applied += count
        pending = attribute_pending_count(runtime.database)
        operation_log(
            configure_logging(),
            operation="attributes",
            status="complete" if pending == 0 else "pending",
            context={"run": batch},
        )
        if pending == 0:
            return applied, None
        if count == 0:
            return applied, error("attribute-drain-stalled", 1)
    return applied, error("attribute-drain-bounded", 1)


def emit(document: dict[str, JsonValue], failed: bool = False) -> int:
    """Write one stable machine-readable CLI result."""
    stream = sys.stderr if failed else sys.stdout
    _ = stream.write(json.dumps(document, sort_keys=True) + "\n")
    return int(failed)


def error(
    code: str,
    status: int,
    details: dict[str, JsonValue] | None = None,
) -> int:
    """Write one stable blocked CLI result."""
    document: dict[str, JsonValue] = {"error": code, "status": "blocked"}
    if details is not None:
        document.update(details)
    _ = sys.stderr.write(json.dumps(document, sort_keys=True) + "\n")
    return status
