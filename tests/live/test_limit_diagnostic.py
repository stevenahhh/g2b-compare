from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from g2b_compare.contracts.diagnostic import (
    LimitDiagnosticConfig,
    inspect_limit_response,
    run_limit_diagnostic,
)
from g2b_compare.contracts.quota import Operation
from tests.acceptance.todo_2_scenarios import quota_manifest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class _Response:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


class _Requester:
    def __init__(self, content: bytes) -> None:
        self.content: bytes = content
        self.calls: int = 0
        self.params: tuple[tuple[str, str], ...] = ()

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> _Response:
        self.calls += 1
        self.params = params
        assert url.endswith(Operation.GET_MAS_CONTRACT_PRODUCT_INFO)
        assert follow_redirects is False
        return _Response(200, {"content-type": "application/json"}, self.content)


def _payload(items: list[dict[str, str]] | dict[str, list[dict[str, str]]]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {
                    "items": items,
                    "numOfRows": 100,
                    "pageNo": 1,
                    "totalCount": 9,
                },
            }
        }
    ).encode()


def test_inspection_reports_direct_and_wrapped_items_without_rows() -> None:
    # Given: direct-list and wrapped-list provider shapes carrying a raw canary.
    direct = _payload([{"name": "raw-item-canary"}])
    wrapped = _payload({"item": [{"name": "raw-item-canary"}]})

    # When: each response is reduced to structural diagnostic evidence.
    observations = (
        inspect_limit_response(200, "application/json", direct),
        inspect_limit_response(200, "application/json", wrapped),
    )

    # Then: item shapes and recursive numeric metadata remain, but rows do not.
    assert [(item.items.shape, item.items.count) for item in observations] == [
        ("direct-list", 1),
        ("wrapped-list", 1),
    ]
    assert [entry.pointer for entry in observations[0].metadata] == [
        "/response/body/numOfRows",
        "/response/body/pageNo",
        "/response/body/totalCount",
    ]
    assert b"raw-item-canary" not in observations[0].model_dump_json().encode()


def test_inspection_reports_missing_numeric_metadata() -> None:
    # Given: a JSON wrapper with no pagination metadata or items.
    content = b'{"response":{"body":{}}}'
    # When: it is structurally inspected.
    result = inspect_limit_response(200, "application/json", content)
    # Then: absence is explicit and safe.
    assert result.metadata == ()
    assert (result.items.shape, result.items.count) == ("missing", 0)


def test_runner_uses_one_d3_limit_call_and_persists_no_secret(
    tmp_path: Path,
) -> None:
    # Given: a persistent quota ledger, memory-loaded key, and fake transport.
    quota = tmp_path / "quota.json"
    _ = quota.write_text(quota_manifest().model_dump_json(), encoding="utf-8")
    secret = tmp_path / "secret.html"
    canary = "secret-value-canary"
    _ = secret.write_text(f'<input id="ServiceKey" value="{canary}">', encoding="utf-8")
    requester = _Requester(_payload([{"raw": canary}]))
    config = LimitDiagnosticConfig(
        output_path=tmp_path / "diagnostic.json",
        ledger_path=tmp_path / "ledger.sqlite3",
        quota_path=quota,
        secret_source=secret,
        observed_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    # When: the diagnostic executes through the injected network-free transport.
    result = run_limit_diagnostic(config, requester)

    # Then: exactly one no-ID D3 limit request is consumed and output is sanitized.
    assert requester.calls == 1
    params = dict(requester.params)
    assert params["numOfRows"] == "1000"
    assert "prdctIdntNo" not in params
    assert params["serviceKey"] == canary
    published = config.output_path.read_bytes()
    assert canary.encode() not in published
    assert b"raw" not in published
    assert result.request_fingerprint in published.decode()
