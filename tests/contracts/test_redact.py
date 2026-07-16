from __future__ import annotations

from g2b_compare.contracts.redact import (
    REDACTED,
    JsonValue,
    redact_json,
    serialize_redacted,
)

CANARY = "SYNTHETIC_SECRET_CANARY_7B2D"


def test_recursive_redaction_is_deterministic_and_secret_safe() -> None:
    # Given: secrets and PII at different nesting depths and insertion orders.
    payload: JsonValue = {
        "z": [{"serviceKey": CANARY, "safe": "kept"}],
        "email": "person@example.invalid",
        "a": {"Authorization": f"Bearer {CANARY}"},
    }

    # When: the payload is recursively redacted and serialized twice.
    first = serialize_redacted(payload, secret_values=(CANARY,))
    second = serialize_redacted(payload, secret_values=(CANARY,))

    # Then: key order is canonical and neither secret nor PII survives.
    assert first == second
    assert CANARY.encode() not in first
    assert b"person@example.invalid" not in first
    assert first.startswith(b'{"a":')


def test_redaction_removes_secrets_from_query_strings_and_free_text() -> None:
    # Given: a key in a URL and the same canary in an unrelated text field.
    payload: JsonValue = {
        "url": f"https://example.invalid/path?serviceKey={CANARY}&pageNo=1",
        "detail": f"token={CANARY}",
    }

    # When: explicit secret values and secret query parameters are redacted.
    redacted = redact_json(payload, secret_values=(CANARY,))

    # Then: the canary is absent everywhere while non-secret structure remains.
    assert redacted == {
        "detail": f"token={REDACTED}",
        "url": f"https://example.invalid/path?serviceKey={REDACTED}&pageNo=1",
    }
