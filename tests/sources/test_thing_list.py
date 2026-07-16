from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from g2b_compare.contracts import manifest as contract_manifest
from g2b_compare.contracts.quota import Operation
from g2b_compare.db.ingest import IngestRepository
from g2b_compare.db.migrate import migrate
from g2b_compare.sources.thing_list import (
    AttributeAdapterError,
    AttributeRequest,
    CompleteAttributeCollection,
    IncompleteAttributeCollection,
    ThingListAdapter,
    assemble_pages,
)
from g2b_compare.sources.thing_list_evidence import AttributeEvidenceStore
from g2b_compare.sync.attribute_quota import AttributeQuotaGate


class _ManifestEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    operation: Operation
    manifest: contract_manifest.ContractManifest


class _ObservedContracts(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    manifests: tuple[_ManifestEntry, ...]


@dataclass(frozen=True, slots=True)
class ResponseStub:
    status_code: int
    content: bytes
    headers: dict[str, str] = field(
        default_factory=lambda: {"content-type": "application/json"}
    )


@dataclass(frozen=True, slots=True)
class RequesterStub:
    response: ResponseStub
    calls: list[tuple[str, tuple[tuple[str, str], ...], bool]] = field(
        default_factory=list
    )

    def get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...],
        follow_redirects: bool,
    ) -> ResponseStub:
        self.calls.append((url, params, follow_redirects))
        return self.response


@dataclass(frozen=True, slots=True)
class FrozenQuotaClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def provider_window_start(self, now: datetime) -> datetime:
        return now - timedelta(hours=1)


def attribute_manifest() -> contract_manifest.ContractManifest:
    observed = _ObservedContracts.model_validate_json(
        Path("docs/api-contract-observed.json").read_bytes()
    )
    selected = next(
        entry.manifest
        for entry in observed.manifests
        if entry.operation is Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE
    )
    return contract_manifest.ContractManifest.model_validate(selected)


def attribute_body(
    *,
    product_id: str = "22065235",
    name: str = "화소수",
    total: int = 1,
    page_no: int = 1,
    page_size: int = 10,
) -> bytes:
    item = {
        "attrNm": name,
        "attrUnit": "pixel",
        "attrVal": "8000000",
        "dtilPrdctClsfcNo": "4512150401",
        "prdctIdntNo": product_id,
        "prdctIdntNoNm": "영상감시장치",
    }
    envelope = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": item},
                "numOfRows": page_size,
                "pageNo": page_no,
                "totalCount": total,
            },
        }
    }
    return json.dumps(envelope, ensure_ascii=False).encode()


def attribute_adapter(
    tmp_path: Path, response: ResponseStub
) -> tuple[ThingListAdapter, RequesterStub]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "thing-list.sqlite3"
    migrate(database)
    manifest = attribute_manifest()
    requester = RequesterStub(response)
    return (
        ThingListAdapter(
            manifest,
            requester,
            "runtime-secret",
            AttributeQuotaGate(
                IngestRepository(database),
                manifest,
                FrozenQuotaClock(datetime(2026, 7, 16, tzinfo=UTC)),
            ),
            AttributeEvidenceStore(database, tmp_path / "raw"),
        ),
        requester,
    )


def test_happy_attribute_join_uses_verified_https_contract(tmp_path: Path) -> None:
    adapter, requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body())
    )
    page = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
    assert tuple(row.source_key for row in page.records) == ('["22065235","화소수",0]',)
    assert page.quarantined == ()
    assert requester.calls[0][0].startswith("https://apis.data.go.kr/1230000/")
    assert requester.calls[0][2] is False


def test_failure_http_only(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body())
    )
    with pytest.raises(AttributeAdapterError, match="http-only"):
        adapter.validate_url("http://apis.data.go.kr/1230000/ao/ThingListInfoService02")


def test_failure_missing_attribute_source_key(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body(name=""))
    )
    page = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
    assert page.records == ()
    assert page.quarantined[0].reason == "missing-attribute-source-key"


def test_failure_wrong_product_id(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body(product_id="99999999"))
    )
    page = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
    assert page.records == ()
    assert page.quarantined[0].reason == "wrong-product-id"


def test_failure_429(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(429, b"rate limited")
    )
    with pytest.raises(AttributeAdapterError, match="429"):
        _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))


def test_failure_malformed_item(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, b'{"response":{"bad":true}}')
    )
    with pytest.raises(AttributeAdapterError, match="malformed-item"):
        _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))


def test_failure_no_data_not_complete_empty(tmp_path: Path) -> None:
    envelope = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {"items": "", "numOfRows": 10, "pageNo": 1, "totalCount": 1},
        }
    }
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, json.dumps(envelope).encode())
    )
    with pytest.raises(AttributeAdapterError, match="no-data-not-complete-empty"):
        _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))


def test_timeout_is_sanitized(tmp_path: Path) -> None:
    @dataclass(frozen=True, slots=True)
    class TimeoutRequester:
        def get(
            self,
            url: str,
            *,
            params: tuple[tuple[str, str], ...],
            follow_redirects: bool,
        ) -> ResponseStub:
            _ = (url, params, follow_redirects)
            message = "secret-url"
            raise httpx.ReadTimeout(message)

    database = tmp_path / "timeout.sqlite3"
    migrate(database)
    manifest = attribute_manifest()
    adapter = ThingListAdapter(
        manifest,
        TimeoutRequester(),
        "runtime-secret",
        AttributeQuotaGate(
            IngestRepository(database),
            manifest,
            FrozenQuotaClock(datetime(2026, 7, 16, tzinfo=UTC)),
        ),
        AttributeEvidenceStore(database, tmp_path / "raw"),
    )
    with pytest.raises(AttributeAdapterError, match="timeout") as captured:
        _ = adapter.fetch_page(AttributeRequest(1, "22065235", 1, 10))
    assert "runtime-secret" not in str(captured.value)


def test_multi_page_collection_reassigns_global_source_ordinal(tmp_path: Path) -> None:
    first_body = attribute_body(total=2, page_size=1)
    second_body = attribute_body(total=2, page_no=2, page_size=1).replace(
        b'"attrVal": "8000000"', b'"attrVal": "4000000"', 1
    )
    adapter1, _requester1 = attribute_adapter(
        tmp_path / "first", ResponseStub(200, first_body)
    )
    adapter2, _requester2 = attribute_adapter(
        tmp_path / "second",
        ResponseStub(200, second_body),
    )
    pages = (
        adapter1.fetch_page(AttributeRequest(1, "22065235", 1, 1)),
        adapter2.fetch_page(AttributeRequest(1, "22065235", 2, 1)),
    )
    collection = assemble_pages(pages)
    assert isinstance(collection, CompleteAttributeCollection)
    assert tuple(record.source_ordinal for record in collection.records) == (0, 1)


def test_partial_multi_page_collection_is_not_complete(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body(total=2, page_size=1))
    )
    collection = assemble_pages(
        (adapter.fetch_page(AttributeRequest(1, "22065235", 1, 1)),)
    )
    assert isinstance(collection, IncompleteAttributeCollection)
    assert collection.reason == "missing-page"
