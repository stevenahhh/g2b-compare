"""Typed live-provider failures eligible for bounded page retry."""

from typing import Final

import httpx

from g2b_compare.contracts.wire import WireContractError
from g2b_compare.sources.envelope import MalformedEnvelopeError, ProviderStatusError
from g2b_compare.sources.shopping_mall import UnsupportedCatalogOperationError
from g2b_compare.sources.transport import (
    AuthenticationTransportError,
    ContentTypeTransportError,
    ContractTransportError,
    RetryableTransportError,
    UnsafeRequestError,
)

TRANSIENT_PROVIDER_FAILURES: Final[tuple[type[Exception], ...]] = (
    httpx.TransportError,
    RetryableTransportError,
)
PERMANENT_PROVIDER_FAILURES: Final[tuple[type[Exception], ...]] = (
    AuthenticationTransportError,
    ContentTypeTransportError,
    ContractTransportError,
    MalformedEnvelopeError,
    ProviderStatusError,
    UnsafeRequestError,
    UnsupportedCatalogOperationError,
    WireContractError,
)


def provider_status_code(error: Exception) -> int:
    """Return the observed HTTP status, or zero when dispatch returned none."""
    if isinstance(
        error,
        AuthenticationTransportError | ContractTransportError,
    ):
        return error.status_code
    if isinstance(error, RetryableTransportError):
        return error.status_code or 0
    if isinstance(
        error,
        (
            ContentTypeTransportError,
            MalformedEnvelopeError,
            ProviderStatusError,
            WireContractError,
        ),
    ):
        return 200
    return 0
