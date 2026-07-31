"""Resumable orchestration for live G2B product-description capture."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Final, Protocol

from playwright.async_api import Error as PlaywrightError
from pydantic import JsonValue, TypeAdapter, ValidationError

from .priority_description import (
    ProductDetailObservation,
    ProductDetailResponseError,
    ProductDetailTarget,
    parse_detail_response,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from g2b_compare.db.models import RawBlobReceipt
    from g2b_compare.db.raw import RawBlobStore

    from .priority_description_store import ProductDescriptionStore

DETAIL_ENDPOINT: Final = (
    "https://shop.g2b.go.kr/gm/gms/gmsf/GdsDtlInfo/"
    "selectGdsDtlInfoMngDtl.do"
)
SUBMISSION_ID: Final = "mf_wfm_container_tab_container1_sbmSrchGdsDtlInfoMngM"
MENU_INFO: Final = (
    '{"menuNo":"11092","menuCangVal":"GMSF001_01",'
    '"bsneClsfCd":"%EC%97%85130034","scrnNo":"02930"}'
)
MAX_RESPONSE_BYTES: Final = 2_000_000
MAX_CONCURRENCY: Final = 20
HTTP_OK: Final = 200
HTTP_RATE_LIMITED: Final = 429
HTTP_SERVER_ERROR: Final = 500
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@dataclass(frozen=True, slots=True)
class FetchedDescriptionResponse:
    """Exact bounded response returned by the authenticated detail endpoint."""

    http_status: int
    content_type: str
    body: bytes


class DescriptionClient(Protocol):
    """Authenticated transport contract used by the resumable crawler."""

    async def fetch(
        self,
        target: ProductDetailTarget,
    ) -> FetchedDescriptionResponse:
        """Fetch one target without classifying or persisting it."""
        ...


@dataclass(frozen=True, slots=True)
class DescriptionCrawlSummary:
    """Terminal counts for one bounded crawl invocation."""

    attempted: int
    stored: int
    missing: int
    failed: int
    remaining: int
    abort_code: str | None


@dataclass(frozen=True, slots=True)
class DescriptionCrawlOptions:
    """Bounded execution policy and optional deterministic test seams."""

    concurrency: int
    observed_at: Callable[[], str] | None = None
    progress: Callable[[DescriptionCrawlSummary], None] | None = None


def description_request_body(target: ProductDetailTarget) -> dict[str, object]:
    """Build the fixed WebSquare request envelope for one product."""
    return {
        "dlGdsDtlInfoMngSrchM": {
            "srchItemIdnfNo": target.product_id,
            "srchCtrtItemMngNo": "",
            "srchParam1": "",
        }
    }


def description_request_headers(target: ProductDetailTarget) -> dict[str, str]:
    """Build only the fixed, secret-free headers required by the endpoint."""
    return {
        "accept": "application/json",
        "content-type": "application/json;charset=UTF-8",
        "submissionid": SUBMISSION_ID,
        "menu-info": MENU_INFO,
        "referer": target.source_url,
        "usr-id": "null",
        "target-id": "tabTitle1",
    }


def description_request_fingerprint(target: ProductDetailTarget) -> str:
    """Hash the reproducible request contract without ambient session headers."""
    contract = {
        "method": "POST",
        "endpoint": DETAIL_ENDPOINT,
        "contractItemManagementNumber": target.contract_item_management_number,
        "headers": description_request_headers(target),
        "body": description_request_body(target),
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


async def crawl_product_descriptions(
    store: ProductDescriptionStore,
    raw_store: RawBlobStore,
    client: DescriptionClient,
    targets: Sequence[ProductDetailTarget],
    options: DescriptionCrawlOptions,
) -> DescriptionCrawlSummary:
    """Attempt each target once, stopping new batches on systemic failure."""
    if not 1 <= options.concurrency <= MAX_CONCURRENCY:
        raise ValueError(options.concurrency)
    clock = options.observed_at or _observed_at
    attempted = stored = missing = failed = 0
    abort_code: str | None = None
    for offset in range(0, len(targets), options.concurrency):
        batch = targets[offset : offset + options.concurrency]
        results = await _fetch_batch(client, raw_store, batch, clock)
        for observation, systemic_code in results:
            _ = store.record(observation)
            attempted += 1
            if observation.outcome == "stored":
                stored += 1
            elif observation.outcome == "missing":
                missing += 1
            else:
                failed += 1
            abort_code = abort_code or systemic_code
        summary = DescriptionCrawlSummary(
            attempted,
            stored,
            missing,
            failed,
            len(targets) - attempted,
            abort_code,
        )
        if options.progress is not None:
            options.progress(summary)
        if abort_code is not None:
            return summary
    return DescriptionCrawlSummary(
        attempted,
        stored,
        missing,
        failed,
        0,
        None,
    )


async def _fetch_batch(
    client: DescriptionClient,
    raw_store: RawBlobStore,
    targets: Sequence[ProductDetailTarget],
    clock: Callable[[], str],
) -> tuple[tuple[ProductDetailObservation, str | None], ...]:
    return tuple(
        await asyncio.gather(
            *(_attempt(client, raw_store, target, clock) for target in targets)
        )
    )


async def _attempt(
    client: DescriptionClient,
    raw_store: RawBlobStore,
    target: ProductDetailTarget,
    clock: Callable[[], str],
) -> tuple[ProductDetailObservation, str | None]:
    fingerprint = description_request_fingerprint(target)
    observed_at = clock()
    try:
        response = await client.fetch(target)
    except TimeoutError:
        return _failure(target, observed_at, "timeout"), None
    except PlaywrightError:
        return _failure(target, observed_at, "transport_error"), None
    if len(response.body) > MAX_RESPONSE_BYTES:
        return _failure(target, observed_at, "response_too_large"), None
    receipt = raw_store.put(response.body, response.content_type)
    error_code, systemic_code = _http_failure(response)
    if error_code is not None:
        return (
            _failure(target, observed_at, error_code, response, receipt),
            systemic_code,
        )
    return _parse_response(target, response, receipt, fingerprint, observed_at)


def _http_failure(
    response: FetchedDescriptionResponse,
) -> tuple[str | None, str | None]:
    if response.http_status in {401, 403}:
        return "session_invalid", "session_invalid"
    if response.http_status == HTTP_RATE_LIMITED:
        return "rate_limited", "rate_limited"
    if response.http_status >= HTTP_SERVER_ERROR:
        return "http_5xx", None
    if response.http_status != HTTP_OK:
        return "http_error", None
    if "json" not in response.content_type.casefold():
        return "session_invalid", "session_invalid"
    return None, None


def _parse_response(
    target: ProductDetailTarget,
    response: FetchedDescriptionResponse,
    receipt: RawBlobReceipt,
    fingerprint: str,
    observed_at: str,
) -> tuple[ProductDetailObservation, str | None]:
    try:
        payload = JSON_ADAPTER.validate_json(response.body)
        content = parse_detail_response(target, payload)
    except (
        ProductDetailResponseError,
        UnicodeDecodeError,
        ValidationError,
    ):
        return (
            _failure(
                target,
                observed_at,
                "contract_changed",
                response,
                receipt,
            ),
            "contract_changed",
        )
    return (
        ProductDetailObservation(
            target=target,
            endpoint_url=DETAIL_ENDPOINT,
            request_fingerprint=fingerprint,
            outcome="missing" if content is None else "stored",
            observed_at=observed_at,
            response_receipt=receipt,
            content=content,
            http_status=response.http_status,
            error_code=None,
        ),
        None,
    )


def _failure(
    target: ProductDetailTarget,
    observed_at: str,
    error_code: str,
    response: FetchedDescriptionResponse | None = None,
    response_receipt: RawBlobReceipt | None = None,
) -> ProductDetailObservation:
    return ProductDetailObservation(
        target=target,
        endpoint_url=DETAIL_ENDPOINT,
        request_fingerprint=description_request_fingerprint(target),
        outcome="failed",
        observed_at=observed_at,
        response_receipt=response_receipt,
        content=None,
        http_status=None if response is None else response.http_status,
        error_code=error_code,
    )


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()
