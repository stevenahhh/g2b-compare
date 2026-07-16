"""Verified individual-attribute HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override
from urllib.parse import urlsplit

import httpx

from g2b_compare.contracts.manifest import (
    ContractManifest,
    VerifiedState,
)
from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.wire import (
    WireContractError,
    official_url,
    parse_page,
)
from g2b_compare.sources.thing_list_evidence import (
    AttributeEvidenceRecord,
    AttributeEvidenceRequest,
    AttributeEvidenceStore,
)
from g2b_compare.sources.thing_list_models import (
    AttributeCollection,
    AttributePage,
    AttributeRecord,
    CompleteAttributeCollection,
    IncompleteAttributeCollection,
    QuarantinedAttribute,
    assemble_pages,
)
from g2b_compare.sources.thing_list_page import (
    AttributePageBuildError,
    AttributePageExpectation,
    build_attribute_page,
)
from g2b_compare.sources.thing_list_response import (
    AttributePageMetadataError,
    parse_attribute_page_metadata,
)

if TYPE_CHECKING:
    from g2b_compare.contracts.wire import Requester
    from g2b_compare.sources.thing_list_evidence import PreparedAttributeEvidence
    from g2b_compare.sync.attribute_quota import AttributeQuotaGate

ATTRIBUTE_OPERATION: Final = Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
HTTP_ONLY: Final = "http-only"
QUOTA_UNVERIFIED: Final = "quota-unverified"
TIMEOUT: Final = "timeout"
RATE_LIMITED: Final = "429"
WRONG_CONTENT_TYPE: Final = "wrong-content-type"
MALFORMED_REQUEST: Final = "malformed-request"
MALFORMED_ITEM: Final = "malformed-item"
HTTP_OK: Final = 200
HTTP_TOO_MANY_REQUESTS: Final = 429

__all__ = (
    "AttributeAdapterError",
    "AttributeCollection",
    "AttributeEvidenceStore",
    "AttributePage",
    "AttributeRecord",
    "AttributeRequest",
    "CompleteAttributeCollection",
    "IncompleteAttributeCollection",
    "QuarantinedAttribute",
    "ThingListAdapter",
    "assemble_pages",
)


@final
class AttributeAdapterError(Exception):
    """Sanitized attribute-adapter failure."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize a public reason without request secrets."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class AttributeRequest:
    """One product-scoped attribute page request."""

    catalog_generation_id: int
    product_id: str
    page_no: int
    page_size: int


@dataclass(frozen=True, slots=True)
class _FreshResponse:
    content: bytes
    content_type: str
    recorded_at: str

    def stage(
        self,
        evidence: AttributeEvidenceStore,
        prepared: PreparedAttributeEvidence,
        item_count: int,
        total_count: int,
    ) -> int:
        return evidence.record(
            prepared,
            AttributeEvidenceRecord(
                self.content,
                self.content_type,
                item_count,
                total_count,
                self.recorded_at,
            ),
        )


@dataclass(frozen=True, slots=True)
class _StoredResponse:
    content: bytes
    content_type: str
    origin_page_id: int

    def stage(
        self,
        evidence: AttributeEvidenceStore,
        prepared: PreparedAttributeEvidence,
        item_count: int,
        total_count: int,
    ) -> int:
        _ = (evidence, prepared, item_count, total_count)
        return self.origin_page_id


type _ResponseContent = _FreshResponse | _StoredResponse


@dataclass(frozen=True, slots=True)
class ThingListAdapter:
    """No-redirect adapter authorized by a verified live manifest."""

    manifest: ContractManifest
    requester: Requester
    service_key: str
    quota_gate: AttributeQuotaGate
    evidence: AttributeEvidenceStore

    def __post_init__(self) -> None:
        """Reject construction without verified operation authorization."""
        _require_verified(self.manifest)

    def validate_url(self, url: str) -> None:
        """Require the exact official HTTPS operation path."""
        if url != official_url(ATTRIBUTE_OPERATION):
            raise AttributeAdapterError(HTTP_ONLY)

    def fetch_page(self, request: AttributeRequest) -> AttributePage:
        """Fetch and parse one bounded page without redirect follow-up."""
        if (
            request.catalog_generation_id < 1
            or not request.product_id
            or request.page_no < 1
            or request.page_size < 1
        ):
            raise AttributeAdapterError(MALFORMED_REQUEST)
        url = official_url(ATTRIBUTE_OPERATION)
        self.validate_url(url)
        keyless_params = (
            ("type", "json"),
            ("pageNo", str(request.page_no)),
            ("numOfRows", str(request.page_size)),
            ("prdctIdntNo", request.product_id),
        )
        now = self.quota_gate.clock.now()
        prepared = self.evidence.prepare(
            AttributeEvidenceRequest(
                request.catalog_generation_id,
                request.product_id,
                request.page_no,
                request.page_size,
                urlsplit(url).path,
                keyless_params,
                now.isoformat(),
            )
        )
        response_content = self._load_or_dispatch(prepared, url, keyless_params)
        content = response_content.content
        content_type = response_content.content_type
        if "application/json" not in content_type.casefold():
            raise AttributeAdapterError(WRONG_CONTENT_TYPE)
        try:
            observed = parse_page(content, ATTRIBUTE_OPERATION)
        except WireContractError:
            raise AttributeAdapterError(MALFORMED_ITEM) from None
        try:
            metadata = parse_attribute_page_metadata(content)
        except AttributePageMetadataError as error:
            raise AttributeAdapterError(str(error)) from None
        origin_page_id = response_content.stage(
            self.evidence,
            prepared,
            len(observed.rows),
            metadata.total_count,
        )
        expectation = AttributePageExpectation(
            request.product_id,
            request.page_no,
            request.page_size,
            _required_fields(self.manifest),
        )
        try:
            return build_attribute_page(
                expectation,
                observed,
                metadata,
                origin_page_id,
            )
        except AttributePageBuildError as error:
            raise AttributeAdapterError(error.reason) from None

    def _load_or_dispatch(
        self,
        prepared: PreparedAttributeEvidence,
        url: str,
        keyless_params: tuple[tuple[str, str], ...],
    ) -> _ResponseContent:
        """Load staged content or reserve quota immediately before dispatch."""
        stored = self.evidence.load(prepared)
        if stored is not None:
            return _StoredResponse(stored.content, stored.content_type, stored.page_id)
        params = (*keyless_params, ("serviceKey", self.service_key))
        reservation = self.quota_gate.reserve()
        try:
            response = self.requester.get(
                url,
                params=params,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            self.quota_gate.finish(reservation, 0)
            raise AttributeAdapterError(TIMEOUT) from None
        self.quota_gate.finish(reservation, response.status_code)
        if response.status_code == HTTP_TOO_MANY_REQUESTS:
            raise AttributeAdapterError(RATE_LIMITED)
        if response.status_code != HTTP_OK:
            reason = f"http-status-{response.status_code}"
            raise AttributeAdapterError(reason)
        return _FreshResponse(
            response.content,
            response.headers.get("content-type", ""),
            reservation.attempted_at.isoformat(),
        )


def _require_verified(manifest: ContractManifest) -> None:
    if manifest.operation is not ATTRIBUTE_OPERATION:
        raise AttributeAdapterError(QUOTA_UNVERIFIED)
    if not isinstance(manifest.state, VerifiedState):
        raise AttributeAdapterError(QUOTA_UNVERIFIED)


def _required_fields(manifest: ContractManifest) -> tuple[str, ...]:
    if isinstance(manifest.state, VerifiedState):
        return manifest.state.required_fields
    raise AttributeAdapterError(QUOTA_UNVERIFIED)
