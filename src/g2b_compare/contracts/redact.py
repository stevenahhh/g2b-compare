"""Deterministic recursive secret redaction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import singledispatch
from re import Match, Pattern
from typing import Final, override

REDACTED: Final = "[REDACTED]"

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_SENSITIVE_KEYS: Final = frozenset(
    {
        "accesskey",
        "accesstoken",
        "accountid",
        "apikey",
        "applicantname",
        "authorization",
        "decodingkey",
        "email",
        "encodingkey",
        "mobile",
        "organization",
        "phone",
        "servicekey",
        "telephone",
        "token",
        "userid",
        "username",
    }
)
_QUERY_PARAMETER_PREFIX: Final = (
    r"(?i)(servicekey|authorization|api[_-]?key|access[_-]?token|"
)
_QUERY_PARAMETER_SUFFIX: Final = r"decodingkey|encodingkey)=([^&\s]+)"
_SECRET_QUERY_PATTERN: Final[Pattern[str]] = re.compile(
    f"{_QUERY_PARAMETER_PREFIX}{_QUERY_PARAMETER_SUFFIX}"
)
_NON_ALNUM_PATTERN: Final[Pattern[str]] = re.compile(r"[^0-9a-z]")


@dataclass(frozen=True, slots=True)
class _UnsupportedJsonValueError(TypeError):
    value_type: str

    @override
    def __str__(self) -> str:
        return f"unsupported JSON value type: {self.value_type}"


def _normalized_key(key: str) -> str:
    return _NON_ALNUM_PATTERN.sub("", key.casefold())


def _redact_query_parameter(match: Match[str]) -> str:
    return f"{match.group(1)}={REDACTED}"


def _redact_text(value: str, secret_values: tuple[str, ...]) -> str:
    redacted = _SECRET_QUERY_PATTERN.sub(_redact_query_parameter, value)
    secrets = sorted(
        (secret for secret in secret_values if secret),
        key=lambda secret: (-len(secret), secret),
    )
    for secret in secrets:
        redacted = redacted.replace(secret, REDACTED)
    return redacted


@singledispatch
def _redact_json_value(
    value: JsonValue,
    secret_values: tuple[str, ...],
) -> JsonValue:
    _ = secret_values
    raise _UnsupportedJsonValueError(value_type=type(value).__name__)


@_redact_json_value.register(type(None))
@_redact_json_value.register(bool)
@_redact_json_value.register(int)
@_redact_json_value.register(float)
def _preserve_scalar(
    value: float | bool | None,
    secret_values: tuple[str, ...],
) -> JsonScalar:
    _ = secret_values
    return value


@_redact_json_value.register(str)
def _redact_string(value: str, secret_values: tuple[str, ...]) -> str:
    return _redact_text(value, secret_values)


@_redact_json_value.register(list)
def _redact_list(
    value: list[JsonValue],
    secret_values: tuple[str, ...],
) -> list[JsonValue]:
    return [_redact_json_value(item, secret_values) for item in value]


@_redact_json_value.register(dict)
def _redact_mapping(
    value: dict[str, JsonValue],
    secret_values: tuple[str, ...],
) -> dict[str, JsonValue]:
    return {
        key: (
            REDACTED
            if _normalized_key(key) in _SENSITIVE_KEYS
            else _redact_json_value(value[key], secret_values)
        )
        for key in sorted(value)
    }


_ = (_preserve_scalar, _redact_string, _redact_list, _redact_mapping)


def redact_json(
    value: JsonValue,
    *,
    secret_values: tuple[str, ...] = (),
) -> JsonValue:
    """Redact nested secret/PII fields and explicit canaries canonically."""
    return _redact_json_value(value, secret_values)


def serialize_redacted(
    value: JsonValue,
    *,
    secret_values: tuple[str, ...] = (),
) -> bytes:
    """Return deterministic compact JSON bytes after recursive redaction."""
    redacted = redact_json(value, secret_values=secret_values)
    return (
        json.dumps(
            redacted,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
