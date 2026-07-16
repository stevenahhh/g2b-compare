from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.wire import official_url
from g2b_compare.sources.envelope import MalformedEnvelopeError
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter, ShoppingMallRequest
from g2b_compare.sources.transport import (
    AuthenticationTransportError,
    ContentTypeTransportError,
    ContractTransportError,
    HttpTransport,
    RetryableTransportError,
    TransportRequest,
)
from tests.sources.test_transport import FakeResponse, ScriptedRequester

NOW = datetime(2026, 7, 16, tzinfo=UTC)
RUNTIME_KEY = "acceptance-secret-never-visible"
DISPATCH_CANARY = "todo5-dispatch-canary-0123456789"
OPERATION = Operation.GET_SHOPPING_MALL_PRODUCT_INFO


def _request() -> ShoppingMallRequest:
    return ShoppingMallRequest(OPERATION, (("pageNo", "1"),), NOW)


def _json(items: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": items,
                    "numOfRows": 10,
                    "pageNo": 1,
                    "totalCount": len(items),
                },
            }
        }
    ).encode()


def test_happy() -> None:
    # Given
    row = {
        "shopngCntrctNo": "C-1",
        "shopngCntrctSno": "1",
        "prdctIdntNo": "P-1",
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": "video surveillance",
        "prdctSpecNm": "8MP",
        "unknown": "preserved",
    }
    requester = ScriptedRequester([FakeResponse(200, "application/json", _json([row]))])
    # When
    page = ShoppingMallAdapter(HttpTransport(requester)).fetch(
        _request(), service_key=RUNTIME_KEY
    )
    # Then
    assert page.records[0].raw_fields["unknown"] == "preserved"
    assert page.records[0].identity.stable_source_key == ("C-1", "1")
    assert RUNTIME_KEY not in page.request_fingerprint


@pytest.mark.parametrize(
    ("scenario", "outcomes", "error_type"),
    [
        ("401-text", [FakeResponse(401, "text/plain")], AuthenticationTransportError),
        ("404-text", [FakeResponse(404, "text/plain")], ContractTransportError),
        (
            "wrong-content-type",
            [FakeResponse(200, "text/plain", b"bad")],
            ContentTypeTransportError,
        ),
        (
            "malformed",
            [FakeResponse(200, "application/json", b"{")],
            MalformedEnvelopeError,
        ),
        (
            "timeout",
            [httpx.ReadTimeout("timeout") for _ in range(3)],
            RetryableTransportError,
        ),
        (
            "429-retry-after",
            [FakeResponse(429, "text/plain", retry_after="7") for _ in range(3)],
            RetryableTransportError,
        ),
        (
            "5xx-exhausted",
            [FakeResponse(503, "text/plain") for _ in range(3)],
            RetryableTransportError,
        ),
        ("secret-url", [FakeResponse(401, "text/plain")], AuthenticationTransportError),
    ],
    ids=(
        "401-text",
        "404-text",
        "wrong-content-type",
        "malformed",
        "timeout",
        "429-retry-after",
        "5xx-exhausted",
        "secret-url",
    ),
)
def test_failure_scenarios(
    scenario: str,
    outcomes: list[FakeResponse | httpx.TimeoutException],
    error_type: type[Exception],
) -> None:
    # Given
    requester = ScriptedRequester(outcomes)
    waits: list[float] = []
    service_key = DISPATCH_CANARY if scenario == "secret-url" else RUNTIME_KEY
    transport = (
        HttpTransport(requester, sleeper=waits.append)
        if scenario == "429-retry-after"
        else HttpTransport(requester)
    )
    adapter = ShoppingMallAdapter(transport)
    # When
    with pytest.raises(error_type) as captured:
        _ = adapter.fetch(_request(), service_key=service_key)
    # Then
    assert RUNTIME_KEY not in str(captured.value)
    assert RUNTIME_KEY not in repr(captured.value)
    if scenario == "401-text":
        assert not isinstance(captured.value, MalformedEnvelopeError)
    if scenario == "429-retry-after":
        assert len(requester.calls) == 3
        assert waits == [7, 7]
        assert isinstance(captured.value, RetryableTransportError)
        assert captured.value.attempts == 3
        assert captured.value.retry_after_seconds == 7
    if scenario == "secret-url":
        dispatch_url, dispatch_params, follow_redirects = requester.calls[0]
        assert ("serviceKey", DISPATCH_CANARY) in dispatch_params
        assert follow_redirects is False
        keyless = TransportRequest(
            OPERATION, official_url(OPERATION), _request().params
        )
        loggable = {
            "url": dispatch_url,
            "error": str(captured.value),
            "error_repr": repr(captured.value),
            "request_fingerprint": keyless.fingerprint(),
        }
        assert DISPATCH_CANARY not in json.dumps(loggable, sort_keys=True)
