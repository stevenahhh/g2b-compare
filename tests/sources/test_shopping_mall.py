from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.shopping_mall import (
    ShoppingMallAdapter,
    ShoppingMallRequest,
    TimestampOrigin,
    UnsupportedCatalogOperationError,
)
from g2b_compare.sources.transport import HttpTransport
from tests.sources.test_transport import FakeResponse, ScriptedRequester

OBSERVED_AT = datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC)
PARAMS = (("pageNo", "1"), ("numOfRows", "10"))
RUNTIME_KEY = "fixture-service-key"
CHANGED = "202607161300"
REGISTERED = "202607151200"
CHANGED_ORIGIN = TimestampOrigin.PROVIDER_CHANGED
REGISTERED_ORIGIN = TimestampOrigin.PROVIDER_REGISTERED
FALLBACK_ORIGIN = TimestampOrigin.OBSERVED_AT_FALLBACK
type TestRow = dict[str, str | dict[str, str]]
type TestItems = list[TestRow] | dict[str, TestRow]


class ContractFixture(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    required_fields: tuple[str, ...]
    sample_stable_key: dict[str, str]


def _row(operation: Operation) -> TestRow:
    fixture_path = Path(f"tests/fixtures/api/shopping/{operation}.json")
    fixture = ContractFixture.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )
    fields = fixture.required_fields
    row: TestRow = {field: f"value-{field}" for field in fields}
    row.update(fixture.sample_stable_key)
    row.update(
        {
            "prdctIdntNo": "23657020",
            "prdctClsfcNo": "46171622",
            "prdctClsfcNoNm": "영상감시장치",
            "dtilPrdctClsfcNo": "4617162201",
            "prdctSpecNm": "8MP 800만화소",
            "cntrctPrceAmt": "1250000",
            "prdctImgUrl": "https://shop.g2b.go.kr/image/product.jpg",
            "rgstDt": "202607151200",
            "futureUnknown": {"nested": "preserved"},
        }
    )
    return row


def _json_page(
    rows: TestItems,
    *,
    page_no: int = 1,
    result_code: str = "00",
) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": result_code, "resultMsg": "OK"},
                "body": {
                    "items": rows,
                    "numOfRows": 10,
                    "pageNo": page_no,
                    "totalCount": len(rows) if isinstance(rows, list) else 1,
                },
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _xml_item(contract_number: str) -> bytes:
    return (
        f"<item><shopngCntrctNo>{contract_number}</shopngCntrctNo>"
        "<shopngCntrctSno>1</shopngCntrctSno><prdctIdntNo>P-1</prdctIdntNo>"
        "<prdctClsfcNo>46171622</prdctClsfcNo><prdctClsfcNoNm>camera"
        "</prdctClsfcNoNm><prdctSpecNm>8MP</prdctSpecNm><rgstDt>20260715"
        "</rgstDt><futureUnknown>kept</futureUnknown></item>"
    ).encode()


def _xml_page(
    items: bytes, *, result_code: str = "00", total_count: int = 1
) -> bytes:
    return (
        b"<response><header><resultCode>"
        + result_code.encode()
        + b"</resultCode><resultMsg>OK</resultMsg></header><body><items>"
        + items
        + b"</items><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>"
        + str(total_count).encode()
        + b"</totalCount></body></response>"
    )


def _request(operation: Operation) -> ShoppingMallRequest:
    return ShoppingMallRequest(
        operation=operation,
        params=PARAMS,
        observed_at=OBSERVED_AT,
    )


@pytest.mark.parametrize("operation", tuple(Operation)[:4])
def test_authorized_json_fixture_becomes_typed_record_with_raw_unknowns(
    operation: Operation,
) -> None:
    # Given
    row = _row(operation)
    items: TestItems = (
        {"item": row}
        if operation is Operation.GET_MAS_CONTRACT_PRODUCT_INFO
        else [row]
    )
    body = _json_page(items)
    requester = ScriptedRequester(
        [FakeResponse(200, "application/json", body)]
    )
    # When
    page = ShoppingMallAdapter(HttpTransport(requester)).fetch(
        _request(operation), service_key=RUNTIME_KEY
    )
    # Then
    record = page.records[0]
    assert record.identity.operation is operation
    assert record.identity.stable_source_key == tuple(
        row[key] for key in ("shopngCntrctNo", "shopngCntrctSno")
    )
    assert record.product_id == "23657020"
    assert record.category_name == "영상감시장치"
    assert record.raw_fields["futureUnknown"] == {"nested": "preserved"}
    assert page.quarantined == ()
    assert (page.raw_response, page.content_type) == (body, "application/json")
def test_json_multi_page_results_remain_page_scoped() -> None:
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    first = _row(operation)
    second = {**_row(operation), "shopngCntrctSno": "7"}
    third = {**_row(operation), "shopngCntrctSno": "8"}
    requester = ScriptedRequester(
        [
            FakeResponse(
                200, "application/json", _json_page([first, third], page_no=1)
            ),
            FakeResponse(200, "application/json", _json_page([second], page_no=2)),
        ]
    )
    adapter = ShoppingMallAdapter(HttpTransport(requester))
    first_page = adapter.fetch(_request(operation), service_key=RUNTIME_KEY)
    second_page = adapter.fetch(
        ShoppingMallRequest(operation, (("pageNo", "2"),), OBSERVED_AT),
        service_key=RUNTIME_KEY,
    )
    assert first_page.page_number == 1
    assert second_page.page_number == 2
    assert [record.identity.stable_source_key[1] for record in first_page.records] == [
        first["shopngCntrctSno"],
        third["shopngCntrctSno"],
    ]
    assert first_page.records[0].identity != second_page.records[0].identity


def test_xml_single_multi_and_no_data_are_typed() -> None:
    operation = Operation.GET_SHOPPING_MALL_PRODUCT_INFO
    body = _xml_page(_xml_item("C-1"))
    requester = ScriptedRequester(
        [
            FakeResponse(200, "application/xml", body),
            FakeResponse(
                200,
                "application/xml",
                _xml_page(_xml_item("C-1") + _xml_item("C-2"), total_count=2),
            ),
            FakeResponse(
                200,
                "application/xml",
                _xml_page(b"", result_code="03", total_count=0),
            ),
        ]
    )
    adapter = ShoppingMallAdapter(HttpTransport(requester))
    single = adapter.fetch(_request(operation), service_key=RUNTIME_KEY)
    multi = adapter.fetch(_request(operation), service_key=RUNTIME_KEY)
    empty = adapter.fetch(_request(operation), service_key=RUNTIME_KEY)
    assert single.records[0].raw_fields["futureUnknown"] == "kept"
    assert single.records[0].identity.stable_source_key == ("C-1", "1")
    assert single.raw_response == body
    assert single.content_type == "application/xml"
    assert [record.identity.stable_source_key[0] for record in multi.records] == [
        "C-1",
        "C-2",
    ]
    assert empty.records == ()
    assert empty.total_count == 0


def test_json_no_data_envelope_is_a_successful_empty_page() -> None:
    operation = Operation.GET_SHOPPING_MALL_PRODUCT_INFO
    requester = ScriptedRequester(
        [FakeResponse(200, "application/json", _json_page([], result_code="03"))]
    )
    page = ShoppingMallAdapter(HttpTransport(requester)).fetch(
        _request(operation), service_key=RUNTIME_KEY
    )
    assert page.records == ()
    assert page.quarantined == ()
    assert page.total_count == 0


def test_missing_stable_source_key_is_quarantined_not_searchable() -> None:
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    row = _row(operation)
    del row["shopngCntrctSno"]
    requester = ScriptedRequester(
        [FakeResponse(200, "application/json", _json_page([row]))]
    )
    page = ShoppingMallAdapter(HttpTransport(requester)).fetch(
        _request(operation), service_key=RUNTIME_KEY
    )
    assert page.records == ()
    assert page.quarantined[0].reason == "missing-stable-source-key"
    assert page.quarantined[0].raw_fields == row


@pytest.mark.parametrize(
    ("changed", "registered", "origin", "value", "precedence"),
    [
        (CHANGED, REGISTERED, CHANGED_ORIGIN, CHANGED, 2),
        (None, REGISTERED, REGISTERED_ORIGIN, REGISTERED, 1),
        (None, None, FALLBACK_ORIGIN, OBSERVED_AT.isoformat(), 0),
    ],
)
def test_timestamp_precedence(
    changed: str | None,
    registered: str | None,
    origin: TimestampOrigin,
    value: str,
    precedence: int,
) -> None:
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    row = _row(operation)
    if changed is None:
        _ = row.pop("chgDt", None)
    else:
        row["chgDt"] = changed
    if registered is None:
        _ = row.pop("rgstDt", None)
    else:
        row["rgstDt"] = registered
    requester = ScriptedRequester(
        [FakeResponse(200, "application/json", _json_page([row]))]
    )
    record = ShoppingMallAdapter(HttpTransport(requester)).fetch(
        _request(operation), service_key=RUNTIME_KEY
    ).records[0]
    assert record.timestamp.value == value
    assert record.timestamp.origin is origin
    assert record.timestamp.precedence == precedence


def test_delivery_operation_is_not_accepted_as_a_catalog_source() -> None:
    requester = ScriptedRequester([])
    with pytest.raises(UnsupportedCatalogOperationError):
        _ = ShoppingMallAdapter(HttpTransport(requester)).fetch(
            _request(Operation.GET_DELIVERY_REQUEST_DETAIL),
            service_key=RUNTIME_KEY,
        )
    assert requester.calls == []
