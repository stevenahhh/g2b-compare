from __future__ import annotations

import json
from typing import TYPE_CHECKING, NoReturn, cast

from g2b_compare import priority_cli
from g2b_compare.priority_description_crawl import DescriptionCrawlSummary
from g2b_compare.priority_description_runtime import (
    LiveDescriptionOptions,
    LiveDescriptionRun,
)
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from g2b_compare.priority_store import PriorityStore
    from g2b_compare.sources.shopping_mall import ShoppingMallAdapter


def test_transient_api_timeout_returns_resumable_status_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(
        store: PriorityStore,
        adapter: ShoppingMallAdapter,
        service_key: str,
        *,
        max_calls: int,
    ) -> NoReturn:
        _ = (store, adapter, service_key, max_calls)
        reason = "timeout"
        raise RetryableTransportError(reason, attempts=3)

    monkeypatch.setenv("G2B_SERVICE_KEY", "test-key")
    monkeypatch.setattr(priority_cli, "crawl_priority_companies", fail)

    status = priority_cli.main(
        ["--database", str(tmp_path / "priority.sqlite3"), "api"]
    )
    output = cast("dict[str, object]", json.loads(capsys.readouterr().out))

    assert status == 0
    assert output == {
        "status": "paused",
        "reason": "timeout",
        "remaining_targets": 0,
    }


def test_crawl_details_runs_resumable_live_enrichment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recorded: dict[str, object] = {}

    async def run(
        database: Path,
        raw_root: Path,
        options: LiveDescriptionOptions,
    ) -> LiveDescriptionRun:
        recorded.update(
            {
                "database": database,
                "raw_root": raw_root,
                "concurrency": options.concurrency,
                "limit": options.limit,
                "retry_missing": options.retry_missing,
                "force": options.force,
            }
        )
        return LiveDescriptionRun(
            summary=DescriptionCrawlSummary(3, 2, 1, 0, 0, None),
            latest_outcomes={"missing": 1, "stored": 2},
            pending_targets=0,
        )

    monkeypatch.setattr(priority_cli, "run_live_product_description_crawl", run)
    database = tmp_path / "priority.sqlite3"

    status = priority_cli.main(
        [
            "--database",
            str(database),
            "crawl-details",
            "--detail-limit",
            "3",
            "--concurrency",
            "4",
            "--retry-missing",
        ]
    )
    output = cast("dict[str, object]", json.loads(capsys.readouterr().out))

    assert status == 0
    assert output == {
        "abort_code": None,
        "attempted": 3,
        "failed": 0,
        "latest_outcomes": {"missing": 1, "stored": 2},
        "missing": 1,
        "pending_targets": 0,
        "remaining": 0,
        "status": "complete",
        "stored": 2,
    }
    assert recorded == {
        "database": database,
        "raw_root": tmp_path / "raw",
        "concurrency": 4,
        "limit": 3,
        "retry_missing": True,
        "force": False,
    }
