from __future__ import annotations

import json
from typing import TYPE_CHECKING, NoReturn, cast

from g2b_compare import priority_cli
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
