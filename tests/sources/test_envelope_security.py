from __future__ import annotations

import json

import pytest

from g2b_compare.db.hashes import sha256_text
from g2b_compare.sources.envelope import (
    MalformedEnvelopeError,
    ProviderStatusError,
    parse_envelope,
)
from g2b_compare.sources.transport import MediaType

REFLECTED_CANARY = "provider-reflected-secret-canary"


def _envelope(result_code: str) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {
                    "resultCode": result_code,
                    "resultMsg": REFLECTED_CANARY,
                },
                "body": {
                    "items": [],
                    "numOfRows": 10,
                    "pageNo": 1,
                    "totalCount": 0,
                },
            }
        },
        separators=(",", ":"),
    ).encode()


def test_provider_failure_exposes_only_result_code_and_message_digest() -> None:
    # Given
    content = _envelope("99")
    # When
    with pytest.raises(ProviderStatusError) as captured:
        _ = parse_envelope(content, MediaType.JSON)
    # Then
    assert REFLECTED_CANARY not in str(captured.value)
    assert REFLECTED_CANARY not in repr(captured.value)
    assert captured.value.result_code == "99"
    assert captured.value.result_message_sha256 == sha256_text(REFLECTED_CANARY)


def test_success_page_stores_message_digest_not_raw_provider_message() -> None:
    # Given
    content = _envelope("00")
    # When
    page = parse_envelope(content, MediaType.JSON)
    # Then
    assert REFLECTED_CANARY not in repr(page)
    assert page.result_message_sha256 == sha256_text(REFLECTED_CANARY)


def test_malformed_envelope_does_not_retain_provider_message_in_exception_chain() -> (
    None
):
    # Given
    content = _envelope("00").replace(b'"numOfRows":10', b'"numOfRows":"bad"')
    # When
    with pytest.raises(MalformedEnvelopeError) as captured:
        _ = parse_envelope(content, MediaType.JSON)
    # Then
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert REFLECTED_CANARY not in repr(captured.value)
