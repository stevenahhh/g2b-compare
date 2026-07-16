from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from g2b_compare.config import AppSettings
from g2b_compare.contracts.capture import (
    CaptureBlockedError,
    CaptureContext,
    capture_all,
)
from g2b_compare.contracts.manifest import VerifiedState, VerifyLimitState
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import RequestInput
from g2b_compare.db.repository import RepositoryContractError
from tests.acceptance.todo_2_scenarios import (
    FakeRequester,
    observe_failure,
    quota_manifest,
    run_happy,
    run_provider_cap_10,
    run_provider_cap_100,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_baseline_local_config_and_request_manifest_are_keyless(
    tmp_path: Path,
) -> None:
    # Given: local settings and a migrated request-manifest store.
    database = tmp_path / "capture.sqlite3"
    migrate(database)
    repository = IngestRepository(database)

    # When: local configuration is loaded and a secret-like parameter is offered.
    settings = AppSettings()
    with pytest.raises(RepositoryContractError, match="secret parameter"):
        _ = repository.register_request(
            RequestInput(
                operation="capture-baseline",
                method="GET",
                official_path="/capture-baseline",
                params=(("serviceKey", "synthetic-canary"),),
                created_at="2026-07-15T00:00:00Z",
            )
        )

    # Then: local config remains keyless and no request row is persisted.
    assert settings.bind_host == "127.0.0.1"


def test_direct_list_json_envelope_reaches_verified_capture() -> None:
    # Given: official success JSON whose body items are a direct list.
    # When: the six-operation capture consumes the wire shape.
    observation = run_happy()
    # Then: all operations complete with one discovery and two verification calls.
    assert (len(observation.captures), observation.http_calls) == (6, 18)


def test_provider_accepted_page_limit_reaches_typed_verified_state() -> None:
    # Given: VERIFY_LIMIT responses capped by the provider at 100 rows.
    # When: all operation contracts complete their three bounded probes.
    observation = run_provider_cap_100()

    # Then: the observed provider limit survives both typed manifest states.
    assert (len(observation.captures), observation.http_calls) == (6, 18)
    for capture in observation.captures:
        limit_state = capture.manifest_history[-2].state
        verified_state = capture.manifest.state
        assert isinstance(limit_state, VerifyLimitState)
        assert isinstance(verified_state, VerifiedState)
        assert limit_state.observed_max_page_size == 100
        assert verified_state.observed_max_page_size == 100
        assert capture.observed_max_page_size == 100
        assert capture.accepted_page_size == 100


def test_positive_provider_limit_is_accepted_and_propagated_exactly() -> None:
    # Given: stable non-empty responses whose VERIFY_LIMIT reports 10 rows.
    # When: capture requests the documented 1000-row candidate.
    observation, requested_page_sizes = run_provider_cap_10()

    # Then: the exact positive provider limit drives manifest pagination.
    assert (len(observation.captures), observation.http_calls) == (6, 18)
    assert requested_page_sizes.count(1000) == 6
    for capture in observation.captures:
        limit_state = capture.manifest_history[-2].state
        verified_state = capture.manifest.state
        assert isinstance(limit_state, VerifyLimitState)
        assert isinstance(verified_state, VerifiedState)
        assert limit_state.accepted_page_size == 10
        assert limit_state.observed_max_page_size == 10
        assert verified_state.accepted_page_size == 10
        assert verified_state.observed_max_page_size == 10
        assert capture.accepted_page_size == 10
        assert capture.observed_max_page_size == 10


def test_missing_provider_page_size_leaves_limit_unproven() -> None:
    # Given: a valid non-empty VERIFY_LIMIT response that omits numOfRows.
    # When: capture validates the provider's page-size evidence.
    observation = observe_failure("limit-size-missing")

    # Then: row count is not substituted for explicit provider evidence.
    assert observation.assertion_class == CaptureBlockedError.__name__
    assert observation.message == (
        "contract capture blocked: limit-unproven (getMASCntrctPrdctInfoList)"
    )
    assert observation.http_calls == 3


def test_limit_validation_failure_is_not_persisted_as_success(tmp_path: Path) -> None:
    # Given: a durable ledger and a limit probe reporting an invalid zero size.
    database = tmp_path / "capture.sqlite3"
    migrate(database)
    repository = IngestRepository(database)
    context = CaptureContext(
        FakeRequester("limit-unproven"),
        repository,
        "synthetic-test-key",
        datetime(2026, 7, 15, tzinfo=UTC),
    )

    # When: operation-level limit validation blocks the capture.
    with pytest.raises(CaptureBlockedError, match="limit-unproven"):
        _ = capture_all(context, quota_manifest())

    # Then: only accepted probes are successes and the rejected probe is failed.
    with sqlite3.connect(database) as connection:
        states = connection.execute(
            "SELECT reservation_state FROM api_call_ledger ORDER BY id"
        ).fetchall()
    assert states == [("succeeded",), ("succeeded",), ("failed",)]


def test_prior_attempts_do_not_consume_restarted_probe_local_budget(
    tmp_path: Path,
) -> None:
    # Given: one persisted failed attempt from an interrupted capture.
    database = tmp_path / "restart.sqlite3"
    migrate(database)
    repository = IngestRepository(database)
    first = CaptureContext(
        FakeRequester("malformed-envelope"),
        repository,
        "synthetic-test-key",
        datetime(2026, 7, 15, tzinfo=UTC),
    )
    with pytest.raises(CaptureBlockedError):
        _ = capture_all(first, quota_manifest())

    # When: a restarted probe needs three discovery candidates and two verifies.
    restarted = FakeRequester("late-discovery")
    context = CaptureContext(
        restarted,
        IngestRepository(database),
        "synthetic-test-key",
        datetime(2026, 7, 15, tzinfo=UTC),
    )
    captures = capture_all(context, quota_manifest())

    # Then: the first operation gets its five local calls and keeps prior usage.
    assert len(captures[0].attempt_ledger_ids) == 5
    assert restarted.calls == 20
    assert (
        repository.quota_usage("getMASCntrctPrdctInfoList", "2026-07-14T00:00:00+00:00")
        == 6
    )
