"""Concrete catalog synchronization and atomic source publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import httpx

from g2b_compare.contracts.live_output import LiveObservedDocument
from g2b_compare.contracts.quota import Operation, effective_ceiling
from g2b_compare.contracts.wire import HttpxRequester, official_url, parse_page
from g2b_compare.db.connection import connect
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.sql import as_int, query
from g2b_compare.observability.logging import configure_logging, operation_log
from g2b_compare.observability.provider_failures import (
    PERMANENT_PROVIDER_FAILURES,
    TRANSIENT_PROVIDER_FAILURES,
    provider_status_code,
)
from g2b_compare.observability.runtime_quota import RuntimeQuotaGate
from g2b_compare.observability.runtime_schedule import (
    PAGE_SIZE,
    SyncMode,
    request_params,
    schedules,
)
from g2b_compare.observability.runtime_source import (
    PageEvidence,
    PagePersistence,
    persist_page,
    run_records,
)
from g2b_compare.sources.shopping_mall import (
    CATALOG_OPERATIONS,
    ShoppingMallAdapter,
    ShoppingMallRequest,
)
from g2b_compare.sources.transport import (
    HttpTransport,
    TransportRequest,
)
from g2b_compare.sync.paginator import PageMeta
from g2b_compare.sync.publisher import PublicationRequest, publish_operation
from g2b_compare.sync.runner import (
    AttemptPage,
    CheckpointStore,
    OperationRunner,
    PageSourceError,
    RunCheckpoint,
    RunResult,
)

HTTP_OK: Final = 200

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.sync.planner import DateWindow, OperationSchedule


@dataclass(frozen=True, slots=True)
class _LivePageSource:
    database: Path
    shopping: ShoppingMallAdapter
    transport: HttpTransport
    service_key: str

    def fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> AttemptPage:
        params = request_params(operation, window, page_no)
        try:
            if operation in CATALOG_OPERATIONS:
                page = self.shopping.fetch(
                    ShoppingMallRequest(operation, params, datetime.now(UTC)),
                    service_key=self.service_key,
                )
                content = page.raw_response
                content_type = page.content_type
                metadata = PageMeta(
                    page.page_number,
                    page.page_size,
                    page.total_count,
                    len(page.records) + len(page.quarantined),
                )
            else:
                response = self.transport.get(
                    TransportRequest(operation, official_url(operation), params),
                    service_key=self.service_key,
                )
                observed = parse_page(response.content, operation)
                content = response.content
                content_type = response.content_type
                metadata = PageMeta(
                    page_no,
                    observed.reported_page_size or PAGE_SIZE,
                    observed.total_count,
                    len(observed.rows),
                )
        except TRANSIENT_PROVIDER_FAILURES as caught:
            raise PageSourceError(
                provider_status_code(caught),
                retryable=True,
            ) from caught
        except PERMANENT_PROVIDER_FAILURES as caught:
            raise PageSourceError(
                provider_status_code(caught),
                retryable=False,
            ) from caught
        _ = persist_page(
            PagePersistence(
                self.database,
                operation,
                window.start.isoformat(),
                window.end.isoformat(),
                params,
                PageEvidence(
                    content,
                    content_type,
                    metadata.page_no,
                    metadata.item_count,
                    metadata.total_count,
                ),
            ),
        )
        operation_log(
            configure_logging(),
            operation=operation.value,
            status="page-persisted",
            context={"window": window.ordinal, "page": page_no},
        )
        return AttemptPage(HTTP_OK, metadata, retryable=False)


def run_catalog_sync(
    database: Path,
    contract: Path,
    service_key: str,
    mode: SyncMode,
) -> tuple[RunResult, ...]:
    """Execute resumable schedules and atomically publish their source rows."""
    document = LiveObservedDocument.model_validate_json(contract.read_bytes())
    quotas = {
        item.operation: effective_ceiling(item.manifest.quota)
        for item in document.manifests
    }
    repository = IngestRepository(database)
    planned = schedules(database, mode, datetime.now(UTC))
    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10),
    ) as client:
        transport = HttpTransport(HttpxRequester(client), max_attempts=1)
        checkpoints = CheckpointStore(database, repository)
        runner = OperationRunner(
            checkpoints,
            RuntimeQuotaGate(repository, quotas),
            _LivePageSource(
                database,
                ShoppingMallAdapter(transport),
                transport,
                service_key,
            ),
        )
        return tuple(
            _run_and_publish(database, checkpoints, runner, schedule)
            for schedule in planned
        )


def _run_and_publish(
    database: Path,
    checkpoints: CheckpointStore,
    runner: OperationRunner,
    schedule: OperationSchedule,
) -> RunResult:
    observed_at = datetime.now(UTC).isoformat()
    checkpoint = _resumable_checkpoint(database, checkpoints, schedule)
    result = runner.run(schedule, observed_at, checkpoint)
    if schedule.windows:
        _ = publish_operation(
            database,
            PublicationRequest(
                schedule.operation,
                schedule.mode,
                schedule.windows[0].start.isoformat(),
                schedule.windows[-1].end.isoformat(),
                observed_at,
                run_records(database, schedule.operation, result.run_id),
                result.validated_pages,
            ),
        )
    operation_log(
        configure_logging(),
        operation=schedule.operation.value,
        status="published",
        context={"run": result.run_id},
    )
    return result


def _resumable_checkpoint(
    database: Path,
    checkpoints: CheckpointStore,
    schedule: OperationSchedule,
) -> RunCheckpoint | None:
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT runs.id FROM sync_runs AS runs
               LEFT JOIN active_source_snapshots AS active
                 ON active.operation=runs.operation
               LEFT JOIN source_snapshots AS snapshots
                 ON snapshots.id=active.snapshot_id
               WHERE runs.operation=? AND runs.mode=?
                 AND (
                   runs.status='running'
                   OR (
                     runs.status='complete'
                     AND (
                       snapshots.published_at IS NULL
                       OR runs.finished_at>snapshots.published_at
                     )
                   )
                 )
               ORDER BY runs.id DESC LIMIT 1""",
            (schedule.operation.value, schedule.mode),
        ).fetchone()
    return None if row is None else checkpoints.load(as_int(row[0]))
