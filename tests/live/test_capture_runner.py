from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

import httpx

from g2b_compare.contracts.live import LiveCaptureConfig, main, run_live_capture
from g2b_compare.contracts.live_output import LiveBlockerRecord, LiveObservedDocument
from g2b_compare.contracts.quota import Operation
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import QuotaReservationInput
from tests.acceptance.todo_2_scenarios import (
    FakeRequester,
    FakeResponse,
    quota_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

NOW = datetime(2026, 7, 15, tzinfo=UTC)
CANARY = "live-runner-{}-canary".format("secret")


class RegistrationNotFoundRequester(FakeRequester):
    @override
    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> FakeResponse:
        if url.endswith(f"/{Operation.GET_SHOPPING_MALL_PRODUCT_INFO}"):
            return FakeResponse(
                404,
                httpx.Headers({"content-type": "text/plain"}),
                b"not found",
            )
        return super().get(url, params=params, follow_redirects=follow_redirects)


class MixedDiscoveryRequester(FakeRequester):
    @override
    def _rows(self, row: dict[str, str], size: int) -> list[dict[str, str]]:
        operation = Operation(self.urls[-1].rsplit("/", maxsplit=1)[-1])
        operation_calls = sum(url.endswith(f"/{operation}") for url in self.urls)
        delayed_operations = (
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
            Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO,
        )
        if operation in delayed_operations and operation_calls <= 2:
            return []
        return super()._rows(row, size)


def _config(tmp_path: Path) -> LiveCaptureConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    quota = tmp_path / "quota.json"
    _ = quota.write_text(quota_manifest().model_dump_json(), encoding="utf-8")
    secret = tmp_path / "secret.html"
    _ = secret.write_text(f'<input value="{CANARY}" id="ServiceKey">', encoding="utf-8")
    return LiveCaptureConfig(
        output_root=tmp_path / "out",
        ledger_path=tmp_path / "ledger.sqlite3",
        quota_path=quota,
        secret_source=secret,
        observed_at=NOW,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _ledger_count(path: Path) -> int:
    repository = IngestRepository(path)
    return sum(
        repository.quota_usage(operation, "2026-07-14T00:00:00+00:00")
        for operation in Operation
    )


def _seed_attempts(path: Path, operation: Operation, count: int) -> None:
    repository = IngestRepository(path)
    for ordinal in range(count):
        _ = repository.reserve_quota(
            QuotaReservationInput(
                operation=operation,
                attempted_at_utc=f"2026-07-15T00:00:0{ordinal}+00:00",
                cutoff_utc="2026-07-14T00:00:00+00:00",
                kst_date="2026-07-15",
                ceiling=1000,
            )
        )


def test_outputs_are_committed_only_after_all_six_operations_verify(
    tmp_path: Path,
) -> None:
    # Given: a persistent ledger and a requester blocked on the first operation.
    config = _config(tmp_path)

    # When: capture fails, then the process is restarted against the same ledger.
    first = run_live_capture(config, FakeRequester("malformed-envelope"))
    second = run_live_capture(config, FakeRequester("late-discovery"))

    # Then: reservations survive restart and the complete verified bundle replaces
    # the first invocation's sanitized blocker.
    assert first.success is False
    assert second.success is True
    assert _ledger_count(config.ledger_path) == 21
    files = _files(config.output_root)
    assert len(files) == 10
    assert ".omo/evidence/task-2-contract/live-blocker.json" not in files
    assert all(CANARY.encode() not in content for content in files.values())


def test_prior_rolling_usage_does_not_consume_a_new_invocation_budget(
    tmp_path: Path,
) -> None:
    # Given: four durable attempts from earlier invocations with ample provider quota.
    config = _config(tmp_path)

    migrate(config.ledger_path)
    _seed_attempts(
        config.ledger_path,
        Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        4,
    )

    # When: a distinct invocation performs the normal three-call capture.
    result = run_live_capture(config, FakeRequester())

    # Then: prior usage remains durable and does not block the new invocation.
    assert result.success is True
    assert _ledger_count(config.ledger_path) == 22


def test_success_writes_deterministic_redacted_contract_bundle(tmp_path: Path) -> None:
    # Given: two clean roots with identical observed inputs and fake wire responses.
    first = _config(tmp_path / "a")
    second = _config(tmp_path / "b")

    # When: all six operations verify independently.
    left = run_live_capture(first, FakeRequester())
    right = run_live_capture(second, FakeRequester())

    # Then: every expected file is byte-identical and contains no secret canary.
    assert left.success is right.success is True
    assert _ledger_count(first.ledger_path) == _ledger_count(second.ledger_path) == 18
    left_files = _files(first.output_root)
    right_files = _files(second.output_root)
    assert left_files == right_files
    assert len(left_files) == 10
    assert all(CANARY.encode() not in content for content in left_files.values())
    observed = LiveObservedDocument.model_validate_json(
        left_files["docs/api-contract-observed.json"]
    )
    assert [item.manifest.state.phase for item in observed.manifests] == [
        "VERIFIED"
    ] * 6
    assert not (first.output_root / ".capture-staging").exists()


def test_success_receipt_records_actual_invocation_http_dispatch_total(
    tmp_path: Path,
) -> None:
    # Given: the same mixed discovery shape as the successful live invocation.
    config = _config(tmp_path)

    # When: all six operations publish one atomic verified bundle.
    result = run_live_capture(config, MixedDiscoveryRequester())

    # Then: the receipt counts the invocation's typed attempt IDs, not 3 per operation.
    assert result.success is True
    observed = LiveObservedDocument.model_validate_json(
        (config.output_root / "docs/api-contract-observed.json").read_bytes()
    )
    assert tuple(len(item.attempt_ledger_ids) for item in observed.manifests) == (
        5,
        5,
        5,
        3,
        3,
        3,
    )
    manual_qa = config.output_root / ".omo/evidence/task-2-contract/manual-qa.json"
    assert manual_qa.read_bytes() == (
        b'{"http_calls":24,"operations_verified":6,"status":"VERIFIED"}\n'
    )


def test_success_does_not_replace_last_good_bundle_on_later_failure(
    tmp_path: Path,
) -> None:
    # Given: a last-good bundle from a successful capture.
    good = _config(tmp_path)
    assert run_live_capture(good, FakeRequester()).success is True
    baseline = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in _files(good.output_root).items()
        if not name.endswith("live-blocker.json")
    }
    failed = LiveCaptureConfig(
        output_root=good.output_root,
        ledger_path=tmp_path / "failed.sqlite3",
        quota_path=good.quota_path,
        secret_source=good.secret_source,
        observed_at=NOW,
    )

    # When: a later independent capture is blocked.
    result = run_live_capture(failed, FakeRequester("401-text"))

    # Then: last-good hashes remain and only the blocker receipt is added.
    assert result.success is False
    after = _files(good.output_root)
    assert baseline == {
        name: hashlib.sha256(content).hexdigest()
        for name, content in after.items()
        if not name.endswith("live-blocker.json")
    }


def test_cli_rejects_secret_values_without_echoing_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: an unsafe attempt to pass a raw key through argv.
    # When: the shipped CLI parses the unsupported option.
    status = main(["--service-key", CANARY])

    # Then: it fails safely without placing the key in output or an exception.
    assert status == 2
    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err


def test_non_success_status_is_sanitized_in_canonical_blocker(tmp_path: Path) -> None:
    # Given: the live runner reaches the registration operation and receives 404.
    config = _config(tmp_path)

    # When: the typed failure is published through the canonical blocker path.
    result = run_live_capture(config, RegistrationNotFoundRequester())

    # Then: only the numeric status fact is retained, never request/secret material.
    assert result.success is False
    content = result.published[0].read_text(encoding="utf-8")
    blocker = LiveBlockerRecord.model_validate_json(content)
    assert blocker.status_code == 404
    assert blocker.operation == Operation.GET_SHOPPING_MALL_PRODUCT_INFO
    assert CANARY not in content
    assert all(name not in content for name in ("url", "query", "body"))
