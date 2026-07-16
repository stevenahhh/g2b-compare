from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.transport import (
    AuthenticationTransportError,
    ContentTypeTransportError,
    ContractTransportError,
    HttpTransport,
    MediaType,
    RetryableTransportError,
    TransportRequest,
    UnsafeRequestError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

RUNTIME_KEY = "never-persist-this-service-key"
URL = (
    "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/"
    "getMASCntrctPrdctInfoList"
)


@dataclass(frozen=True, slots=True)
class FakeResponse:
    status_code: int
    content_type: str
    content: bytes = b"{}"
    retry_after: str | None = None

    @property
    def headers(self) -> Mapping[str, str]:
        retry_header = (
            {} if self.retry_after is None else {"retry-after": self.retry_after}
        )
        return {"content-type": self.content_type, **retry_header}


class ScriptedRequester:
    """Deterministic wire fake that retains request call facts."""

    def __init__(self, outcomes: list[FakeResponse | httpx.TimeoutException]) -> None:
        self._outcomes: list[FakeResponse | httpx.TimeoutException] = outcomes
        self.calls: list[tuple[str, tuple[tuple[str, str], ...], bool]] = []

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> FakeResponse:
        self.calls.append((url, params, follow_redirects))
        outcome = self._outcomes[len(self.calls) - 1]
        if isinstance(outcome, httpx.TimeoutException):
            raise outcome
        return outcome


def request() -> TransportRequest:
    return TransportRequest(
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        url=URL,
        params=(("pageNo", "1"), ("numOfRows", "10")),
    )


def test_json_response_uses_official_https_without_redirects() -> None:
    # Given
    requester = ScriptedRequester(
        [FakeResponse(200, "application/json; charset=utf-8", b'{"ok":true}')]
    )
    # When
    response = HttpTransport(requester).get(request(), service_key=RUNTIME_KEY)
    # Then
    assert response.media_type is MediaType.JSON
    assert response.content == b'{"ok":true}'
    assert requester.calls == [
        (
            URL,
            (("serviceKey", RUNTIME_KEY), ("pageNo", "1"), ("numOfRows", "10")),
            False,
        )
    ]
    assert RUNTIME_KEY not in response.request_fingerprint


@pytest.mark.parametrize("status", [401, 403])
def test_plain_auth_failure_is_classified_before_decoding(status: int) -> None:
    # Given
    requester = ScriptedRequester([FakeResponse(status, "text/plain", b"denied")])
    # When / Then
    with pytest.raises(AuthenticationTransportError) as captured:
        _ = HttpTransport(requester).get(request(), service_key=RUNTIME_KEY)
    assert captured.value.status_code == status
    assert RUNTIME_KEY not in repr(captured.value)


def test_404_is_a_contract_error_before_decoding() -> None:
    requester = ScriptedRequester([FakeResponse(404, "text/plain", b"missing")])
    with pytest.raises(ContractTransportError, match="HTTP 404"):
        _ = HttpTransport(requester).get(request(), service_key=RUNTIME_KEY)


def test_wrong_content_type_is_rejected_before_body_parsing() -> None:
    requester = ScriptedRequester([FakeResponse(200, "text/plain", b"not-json")])
    with pytest.raises(ContentTypeTransportError, match="text/plain"):
        _ = HttpTransport(requester).get(request(), service_key=RUNTIME_KEY)


def test_429_retries_are_bounded_and_honors_retry_after_before_exhaustion() -> None:
    # Given
    requester = ScriptedRequester(
        [FakeResponse(429, "text/plain", retry_after="120") for _ in range(3)]
    )
    waits: list[float] = []
    # When
    with pytest.raises(RetryableTransportError) as captured:
        _ = HttpTransport(requester, max_attempts=3, sleeper=waits.append).get(
            request(), service_key=RUNTIME_KEY
        )
    # Then
    assert captured.value.retry_after_seconds == 120
    assert captured.value.attempts == 3
    assert captured.value.status_code == 429
    assert len(requester.calls) == 3
    assert waits == [120, 120]
    assert RUNTIME_KEY not in str(captured.value)


def test_5xx_retries_are_bounded_and_report_exhaustion() -> None:
    requester = ScriptedRequester([FakeResponse(503, "text/plain") for _ in range(3)])
    with pytest.raises(RetryableTransportError) as captured:
        _ = HttpTransport(requester, max_attempts=3).get(
            request(), service_key=RUNTIME_KEY
        )
    assert captured.value.status_code == 503
    assert captured.value.attempts == 3
    assert len(requester.calls) == 3


def test_timeout_retries_are_bounded() -> None:
    requester = ScriptedRequester(
        [httpx.ReadTimeout("bounded timeout") for _ in range(2)]
    )
    with pytest.raises(RetryableTransportError) as captured:
        _ = HttpTransport(requester, max_attempts=2).get(
            request(), service_key=RUNTIME_KEY
        )
    assert captured.value.reason == "timeout"
    assert captured.value.attempts == 2


@pytest.mark.parametrize(
    ("url", "params"),
    [
        (URL.replace("https://", "http://"), (("pageNo", "1"),)),
        (URL.replace("apis.data.go.kr", "example.invalid"), (("pageNo", "1"),)),
        (URL, (("serviceKey", RUNTIME_KEY),)),
    ],
)
def test_request_rejects_nonofficial_or_secret_bearing_inputs(
    url: str,
    params: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(UnsafeRequestError):
        _ = TransportRequest(
            operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
            url=url,
            params=params,
        )
