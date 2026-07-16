from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from g2b_compare.contracts.capture import (
    CaptureBlockedError,
    CaptureContext,
    OperationCapture,
    capture_all,
)
from g2b_compare.contracts.probe import attempt_probe
from g2b_compare.contracts.quota import (
    Operation,
    QuotaManifest,
    QuotaRow,
    service_id_for,
)
from g2b_compare.contracts.wire import WireContractError, official_url
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.db.models import QuotaReservationInput

NOW = datetime(2026, 7, 15, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FakeResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str
    http_calls: int


@dataclass(frozen=True, slots=True)
class HappyObservation:
    captures: tuple[OperationCapture, ...]
    http_calls: int


class FakeRequester:
    def __init__(self, mode: str = "happy") -> None:
        self.mode: str = mode
        self.calls: int = 0
        self.urls: list[str] = []
        self.requested_page_sizes: list[int] = []
        self.share_calls: int = 0
        self.redirect_target_calls: int = 0

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> FakeResponse:
        self.calls += 1
        self.urls.append(url)
        assert follow_redirects is False
        if url.startswith("https://redirect.invalid/"):
            self.redirect_target_calls += 1
        if url.startswith("https://shop.g2b.go.kr/"):
            self.share_calls += 1
            return FakeResponse(
                302,
                httpx.Headers({"location": "https://redirect.invalid/followed"}),
                b"",
            )
        assert url.startswith("https://apis.data.go.kr/1230000/")
        assert sum(key == "serviceKey" for key, _value in params) == 1
        size = int(dict(params)["numOfRows"])
        self.requested_page_sizes.append(size)
        operation = url.rsplit("/", maxsplit=1)[-1]
        failure = self._failure_response()
        if failure is not None:
            return failure
        row = _row(operation)
        if self.mode == "share-field":
            row["ctrtItemMngNo"] = "UNVERIFIED-TRANSIENT"
        rows = self._rows(row, size)
        if self.mode == "stable-key-missing":
            _ = rows[0].pop(next(iter(rows[0])))
        reported_size = (
            {
                "provider-cap-10": 10,
                "provider-cap-100": 100,
                "limit-unproven": 0,
            }.get(self.mode, size)
            if size == 1000
            else size
        )
        body: dict[str, str | int | list[dict[str, str]]] = {
            "items": rows,
            "numOfRows": reported_size,
            "pageNo": 1,
            "totalCount": len(rows),
        }
        if self.mode == "limit-size-missing" and size == 1000:
            _ = body.pop("numOfRows")
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": body,
            }
        }
        if self.mode == "provisional-schema-not-strict" and self.calls == 2:
            body["unexpected"] = "not-allowed"
        return FakeResponse(
            200,
            httpx.Headers({"content-type": "application/json;charset=UTF-8"}),
            json.dumps(payload, separators=(",", ":")).encode(),
        )

    def _failure_response(self) -> FakeResponse | None:
        match self.mode:
            case "401-text":
                return FakeResponse(
                    401, httpx.Headers({"content-type": "text/plain"}), b"denied"
                )
            case "200-wrong-content-type":
                return FakeResponse(
                    200, httpx.Headers({"content-type": "text/html"}), b"{}"
                )
            case "malformed-envelope":
                return FakeResponse(
                    200,
                    httpx.Headers({"content-type": "application/json"}),
                    b"{}",
                )
            case "redirect-response-zero-followup":
                return FakeResponse(
                    302,
                    httpx.Headers({"location": "https://example.invalid"}),
                    b"",
                )
            case "retry-leaves-no-verification-budget":
                return FakeResponse(
                    503, httpx.Headers({"content-type": "text/plain"}), b""
                )
            case _:
                return None

    def _rows(self, row: dict[str, str], size: int) -> list[dict[str, str]]:
        if self.mode == "all-discovery-empty" or (
            self.mode == "late-discovery" and self.calls <= 2
        ):
            return []
        if self.mode == "verification-empty" and size > 1:
            return []
        if self.mode == "stable-key-duplicate" and size > 1:
            return [row, row.copy()]
        return [row]


def run_happy() -> HappyObservation:
    requester = FakeRequester()
    captures = _capture(requester, quota_manifest())
    assert all(capture.transitions[-1] == "VERIFIED" for capture in captures)
    return HappyObservation(captures, requester.calls)


def run_provider_cap_100() -> HappyObservation:
    requester = FakeRequester("provider-cap-100")
    captures = _capture(requester, quota_manifest())
    return HappyObservation(captures, requester.calls)


def run_provider_cap_10() -> tuple[HappyObservation, tuple[int, ...]]:
    requester = FakeRequester("provider-cap-10")
    captures = _capture(requester, quota_manifest())
    return HappyObservation(captures, requester.calls), tuple(
        requester.requested_page_sizes
    )


def observe_failure(scenario: str) -> FailureObservation:
    if scenario in {
        "missing-attribute-quota-row",
        "quota-unknown",
        "quota-row-not-approved",
        "attribute-call-before-quota",
    }:
        requester = FakeRequester()
        with pytest.raises(ValidationError) as observed:
            _ = _invalid_quota(scenario)
        assert requester.calls == 0
        return FailureObservation(
            type(observed.value).__name__, str(observed.value), requester.calls
        )
    if scenario == "attribute-http-only":
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "g2b_compare.contracts.wire.G2B_ATTRIBUTE_API_BASE_URL",
                "http://apis.data.go.kr/1230000/ao/ThngListInfoService02",
            )
            with pytest.raises(
                WireContractError, match="attribute-http-only"
            ) as observed:
                _ = official_url(Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE)
        return FailureObservation(type(observed.value).__name__, str(observed.value), 0)
    if scenario in {"unverified-share-field", "share-preflight-redirect"}:
        return _observe_share(scenario)
    if scenario == "probe-budget-below-three":
        return _observe_persisted_probe_budget()
    if scenario == "probe-call-6":
        return _observe_probe_call_limit()
    requester = FakeRequester(scenario)
    low_budget = scenario == "low-quota-zero-call"
    quota = quota_manifest(daily_quota=100 if low_budget else 1000)
    key = "" if scenario == "missing-key" else "synthetic-test-key"
    with pytest.raises(CaptureBlockedError) as observed:
        _ = _capture(requester, quota, key)
    expected_reason = (
        {
            "limit-size-missing": "limit-unproven",
            "provisional-schema-not-strict": "malformed-envelope",
        }.get(scenario, scenario)
    )
    assert observed.value.reason == expected_reason
    if scenario in {"low-quota-zero-call", "missing-key"}:
        assert requester.calls == 0
    if scenario in {
        "401-text",
        "200-wrong-content-type",
        "malformed-envelope",
        "redirect-response-zero-followup",
        "stable-key-missing",
    }:
        assert requester.calls == 1
    expected_multi_call_count = {
        "all-discovery-empty": 3,
        "retry-leaves-no-verification-budget": 3,
        "verification-empty": 2,
        "stable-key-duplicate": 2,
        "limit-size-missing": 3,
        "limit-unproven": 3,
        "provisional-schema-not-strict": 2,
    }.get(scenario)
    if expected_multi_call_count is not None:
        assert requester.calls == expected_multi_call_count
    if scenario == "redirect-response-zero-followup":
        assert len(requester.urls) == 1
    return FailureObservation(
        type(observed.value).__name__, str(observed.value), requester.calls
    )


def _observe_share(scenario: str) -> FailureObservation:
    if scenario == "unverified-share-field":
        requester = FakeRequester("share-field")
        captures = _capture(requester, quota_manifest())
        assert all(capture.deep_link_supported is False for capture in captures)
        assert all(
            capture.share_link_preflight.outcome == "not-attempted"
            for capture in captures
        )
        assert all(url.startswith("https://apis.data.go.kr/") for url in requester.urls)
        return FailureObservation(
            OperationCapture.__name__,
            "deep-link-supported=false; share-link-preflight=not-attempted",
            requester.calls,
        )
    requester = FakeRequester("share-preflight-redirect")
    captures = _capture(
        requester,
        quota_manifest(),
        share_candidate_url="https://shop.g2b.go.kr/share/candidate",
    )
    assert requester.share_calls == len(captures) == 6
    assert requester.redirect_target_calls == 0
    assert all(capture.deep_link_supported is False for capture in captures)
    assert all(
        capture.share_link_preflight.outcome == "redirect-rejected"
        and capture.share_link_preflight.status_code == 302
        and "location" not in capture.share_link_preflight.model_fields_set
        for capture in captures
    )
    return FailureObservation(
        OperationCapture.__name__,
        "deep-link-supported=false; share-link-preflight=redirect-rejected",
        requester.calls,
    )


def _observe_persisted_probe_budget() -> FailureObservation:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "capture.sqlite3"
        migrate(database)
        repository = IngestRepository(database)
        for ordinal in range(898):
            _ = repository.reserve_quota(
                QuotaReservationInput(
                    operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                    attempted_at_utc=(
                        f"2026-07-15T00:{ordinal // 60:02d}:"
                        f"{ordinal % 60:02d}+00:00"
                    ),
                    cutoff_utc="2026-07-14T00:00:00+00:00",
                    kst_date="2026-07-15",
                    ceiling=900,
                )
            )
        requester = FakeRequester()
        context = CaptureContext(requester, repository, "synthetic-test-key", NOW)
        with pytest.raises(
            CaptureBlockedError, match="probe-budget-below-three"
        ) as observed:
            _ = capture_all(context, quota_manifest())
        assert requester.calls == 0
        return FailureObservation(
            type(observed.value).__name__, str(observed.value), requester.calls
        )


def _observe_probe_call_limit() -> FailureObservation:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "capture.sqlite3"
        migrate(database)
        repository = IngestRepository(database)
        prior_attempt_ledger_ids = [
            repository.reserve_quota(
                QuotaReservationInput(
                    operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                    attempted_at_utc=f"2026-07-15T00:00:0{ordinal}+00:00",
                    cutoff_utc="2026-07-14T00:00:00+00:00",
                    kst_date="2026-07-15",
                    ceiling=900,
                )
            )
            for ordinal in range(4)
        ]
        requester = FakeRequester()
        current_attempts: list[int] = []
        context = CaptureContext(requester, repository, "synthetic-test-key", NOW)
        params = (("type", "json"), ("pageNo", "1"), ("numOfRows", "1"))
        for _ordinal in range(5):
            _ = attempt_probe(
                context,
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                params,
                900,
                current_attempts,
            )
        with pytest.raises(CaptureBlockedError, match="probe-call-6") as observed:
            _ = attempt_probe(
                context,
                Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
                params,
                900,
                current_attempts,
            )
        persisted_attempts = repository.quota_usage(
            Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            "2026-07-14T00:00:00+00:00",
        )
        assert persisted_attempts == len(prior_attempt_ledger_ids) + 5 == 9
        assert requester.calls == 5
        assert len(current_attempts) == 5
        assert observed.value.http_calls == 5
        return FailureObservation(
            type(observed.value).__name__, str(observed.value), requester.calls
        )


def _capture(
    requester: FakeRequester,
    quota: QuotaManifest,
    key: str = "synthetic-test-key",
    share_candidate_url: str | None = None,
) -> tuple[OperationCapture, ...]:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "capture.sqlite3"
        migrate(database)
        repository = IngestRepository(database)
        if share_candidate_url is None:
            context = CaptureContext(requester, repository, key, NOW)
        else:
            context = CaptureContext(
                requester=requester,
                repository=repository,
                service_key=key,
                observed_at=NOW,
                share_candidate_url=share_candidate_url,
            )
        return capture_all(context, quota)


def quota_manifest(daily_quota: int = 1000) -> QuotaManifest:
    rows = tuple(
        QuotaRow.model_validate(
            {
                "service_id": service_id_for(operation),
                "operation": operation,
                "approved": True,
                "daily_quota": daily_quota,
                "reset_timezone": "unknown",
                "reset_window": "unknown",
                "observed_at": NOW,
                "source_sha256": "a" * 64,
            }
        )
        for operation in Operation
    )
    return QuotaManifest(rows=rows)


def _invalid_quota(scenario: str) -> QuotaManifest:
    payloads = [row.model_dump(mode="json") for row in quota_manifest().rows]
    if scenario in {"missing-attribute-quota-row", "attribute-call-before-quota"}:
        _ = payloads.pop()
    elif scenario == "quota-unknown":
        payloads[0]["daily_quota"] = "unknown"
    elif scenario == "quota-row-not-approved":
        payloads[0]["approved"] = False
    return QuotaManifest.model_validate({"rows": payloads})


def _row(operation: str) -> dict[str, str]:
    if operation == Operation.GET_DELIVERY_REQUEST_DETAIL:
        return {"dlvrReqNo": "D-1", "dlvrReqChgOrd": "00", "prdctSno": "1"}
    if operation == Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE:
        return {"prdctIdntNo": "22065235", "attrNm": "resolution"}
    return {"shopngCntrctNo": "C-1", "shopngCntrctSno": "1"}
