"""Safe common HTTP boundary for official G2B APIs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import sleep
from typing import TYPE_CHECKING, Final, override
from urllib.parse import urlsplit

import httpx

from g2b_compare.contracts.wire import Requester, official_url
from g2b_compare.db.hashes import request_identity
from g2b_compare.db.models import RequestInput

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from g2b_compare.contracts.quota import Operation

DEFAULT_MAX_ATTEMPTS: Final = 3
SERVICE_KEY_NAME: Final = "serviceKey"
AUTH_STATUSES: Final = frozenset({401, 403})
NOT_FOUND_STATUS: Final = 404
RATE_LIMIT_STATUS: Final = 429
SERVER_ERROR_MIN: Final = 500
SUCCESS_MIN: Final = 200
SUCCESS_MAX: Final = 300
URL_REASON: Final = "URL must equal the official HTTPS operation URL"
KEY_REASON: Final = "service key must remain runtime-only"
DUPLICATE_REASON: Final = "request parameter names must be unique"
ATTEMPT_REASON: Final = "max attempts must be positive"
TIMEOUT_REASON: Final = "timeout"
RATE_LIMIT_REASON: Final = "rate-limit"
SERVER_REASON: Final = "server-error"
EXHAUSTED_REASON: Final = "attempts-exhausted"


class MediaType(StrEnum):
    """Supported provider payload families."""

    JSON = "json"
    XML = "xml"


@dataclass(frozen=True, slots=True)
class UnsafeRequestError(Exception):
    """A request is not keyless or does not target its official URL."""

    reason: str

    @override
    def __str__(self) -> str:
        return f"unsafe G2B request: {self.reason}"


@dataclass(frozen=True, slots=True)
class AuthenticationTransportError(Exception):
    """A permanent provider authentication rejection."""

    status_code: int

    @override
    def __str__(self) -> str:
        return f"permanent authentication error: HTTP {self.status_code}"


@dataclass(frozen=True, slots=True)
class ContractTransportError(Exception):
    """A non-retryable provider HTTP contract rejection."""

    status_code: int

    @override
    def __str__(self) -> str:
        return f"provider contract error: HTTP {self.status_code}"


@dataclass(frozen=True, slots=True)
class ContentTypeTransportError(Exception):
    """A successful response declared an unsupported payload type."""

    content_type: str

    @override
    def __str__(self) -> str:
        return f"unsupported provider content type: {self.content_type}"


@dataclass(frozen=True, slots=True)
class RetryableTransportError(Exception):
    """A bounded transient provider failure ready for later scheduling."""

    reason: str
    attempts: int
    status_code: int | None = None
    retry_after_seconds: int | None = None

    @override
    def __str__(self) -> str:
        status = "timeout" if self.status_code is None else f"HTTP {self.status_code}"
        return f"retryable provider error after {self.attempts} attempt(s): {status}"


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """One keyless request bound to an exact observed operation URL."""

    operation: Operation
    url: str
    params: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Reject nonofficial, secret-bearing, or ambiguous inputs."""
        if self.url != official_url(self.operation):
            raise UnsafeRequestError(URL_REASON)
        keys = tuple(_normalized_key(key) for key, _value in self.params)
        if "servicekey" in keys:
            raise UnsafeRequestError(KEY_REASON)
        if len(keys) != len(set(keys)):
            raise UnsafeRequestError(DUPLICATE_REASON)

    def fingerprint(self) -> str:
        """Return the shared deterministic keyless request fingerprint."""
        _params_json, _params_sha, fingerprint = request_identity(
            RequestInput(
                operation=self.operation,
                method="GET",
                official_path=urlsplit(self.url).path,
                params=self.params,
                created_at="",
            )
        )
        return fingerprint


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """A status-checked response with its secret-free request identity."""

    content: bytes
    media_type: MediaType
    content_type: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class HttpTransport:
    """Bounded no-redirect transport over an injected request capability."""

    requester: Requester
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    sleeper: Callable[[float], None] = sleep

    def __post_init__(self) -> None:
        """Reject a transport that could perform zero attempts."""
        if self.max_attempts < 1:
            raise UnsafeRequestError(ATTEMPT_REASON)

    def get(self, request: TransportRequest, *, service_key: str) -> TransportResponse:
        """Execute a bounded request after enforcing the safe wire contract."""
        params = ((SERVICE_KEY_NAME, service_key), *request.params)
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.requester.get(
                    request.url,
                    params=params,
                    follow_redirects=False,
                )
            except httpx.TimeoutException:
                if attempt == self.max_attempts:
                    raise RetryableTransportError(
                        TIMEOUT_REASON, attempts=attempt
                    ) from None
                continue
            status = response.status_code
            if status in AUTH_STATUSES:
                raise AuthenticationTransportError(status)
            if status == NOT_FOUND_STATUS:
                raise ContractTransportError(status)
            if status == RATE_LIMIT_STATUS:
                self._retry_rate_limit(response.headers, attempt)
                continue
            if status >= SERVER_ERROR_MIN:
                if attempt == self.max_attempts:
                    raise RetryableTransportError(
                        SERVER_REASON, attempts=attempt, status_code=status
                    )
                continue
            if status < SUCCESS_MIN or status >= SUCCESS_MAX:
                raise ContractTransportError(status)
            content_type = _header(response.headers, "content-type")
            media_type = _media_type(content_type)
            return TransportResponse(
                content=response.content,
                media_type=media_type,
                content_type=content_type,
                request_fingerprint=request.fingerprint(),
            )
        raise RetryableTransportError(EXHAUSTED_REASON, attempts=self.max_attempts)

    def _retry_rate_limit(self, headers: Mapping[str, str], attempt: int) -> None:
        retry_after_seconds = _retry_after(headers)
        if attempt == self.max_attempts:
            raise RetryableTransportError(
                RATE_LIMIT_REASON,
                attempts=attempt,
                status_code=RATE_LIMIT_STATUS,
                retry_after_seconds=retry_after_seconds,
            )
        if retry_after_seconds is not None:
            self.sleeper(retry_after_seconds)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.casefold() == name:
            return value.strip()
    return ""


def _retry_after(headers: Mapping[str, str]) -> int | None:
    value = _header(headers, "retry-after")
    return int(value) if value.isdecimal() else None


def _media_type(content_type: str) -> MediaType:
    family = content_type.partition(";")[0].strip().casefold()
    media_types = {
        "application/json": MediaType.JSON,
        "text/json": MediaType.JSON,
        "application/xml": MediaType.XML,
        "text/xml": MediaType.XML,
    }
    try:
        return media_types[family]
    except KeyError:
        raise ContentTypeTransportError(content_type) from None
