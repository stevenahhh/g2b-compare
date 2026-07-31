"""Product-description parsing and append-only persistence contracts."""

from __future__ import annotations

import html
import json
import sqlite3
from hashlib import sha256
from typing import TYPE_CHECKING, final

import pytest

from g2b_compare.db.prune import RawRetentionRepository
from g2b_compare.db.raw import RawBlobStore
from g2b_compare.db.sql import as_int, query
from g2b_compare.priority_description import (
    ProductDetailObservation,
    ProductDetailResponseError,
    ProductDetailTarget,
    parse_detail_response,
)
from g2b_compare.priority_description_crawl import (
    DescriptionCrawlOptions,
    FetchedDescriptionResponse,
    crawl_product_descriptions,
    description_request_fingerprint,
)
from g2b_compare.priority_description_store import ProductDescriptionStore
from g2b_compare.priority_store import PriorityStore

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

TARGET_URL = (
    "https://shop.g2b.go.kr/link/GMSF001_01/"
    "?ctrtItemMngNo=0023H0531_1000000005"
)
ENDPOINT_URL = (
    "https://shop.g2b.go.kr/gm/gms/gmsf/GdsDtlInfo/"
    "selectGdsDtlInfoMngDtl.do"
)
REQUEST_FINGERPRINT = "a" * 64
TARGET = ProductDetailTarget(
    product_id="25044539",
    contract_item_management_number="0023H0531_1000000005",
    source_url=TARGET_URL,
)
DETAIL_HTML = """
<div class="detailWrap">
  <p>KN-PC200CPS, 주차주제어장치, 통합관리서버</p>
  <p>물품식별번호:25044539</p>
  <img src="/ignored-product-image.png" alt="상품 이미지">
  <p>※ 통합관리서버</p>
  <p>로컬에 설치된 기기 결제 관련 데이터를 통합하여 관리한다.</p>
  <p>※ 제원</p>
  <p>① CPU : 16Core 2.3Ghz<br>② RAM : 32GB<br>③ HDD : 1TB</p>
</div>
""".strip()


def _response(detail_html: str | None = DETAIL_HTML) -> dict[str, object]:
    return {
        "ErrorCode": "0",
        "ErrorMsg": "",
        "dlGdsDtlInfoMngM": {
            "itemIdnfNo": TARGET.product_id,
            "bulkItemDtlDscr": (
                "" if detail_html is None else html.escape(detail_html, quote=True)
            ),
        },
    }


def _seed_product(database: Path, target: ProductDetailTarget) -> None:
    _ = PriorityStore(database)
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            """
            INSERT INTO priority_products
            (product_id, operation, contract_number, contract_sequence,
            category_number, category_name, detail_category_number, spec,
            company_name, unit, price_won, contract_method, delivery_condition,
            delivery_days, contract_end_date, image_url, detail_url, raw_json,
            observed_at, site_status, site_crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target.product_id,
                "getShoppingMallPrdctInfoList",
                "0023H0531",
                "1",
                "46161500",
                "주차관제장치",
                "4616150001",
                "KN-PC200CPS",
                "주식회사 코리아넷",
                "대",
                1,
                "다수공급자계약",
                "납품장소도",
                "30",
                "20271231",
                "",
                target.source_url,
                "{}",
                "2026-07-31T00:00:00+00:00",
                "ok",
                "2026-07-31T00:00:00+00:00",
            ),
        )


def _stored_observation(
    raw_store: RawBlobStore,
    observed_at: str,
) -> ProductDetailObservation:
    content = parse_detail_response(TARGET, _response())
    assert content is not None
    receipt = raw_store.put(b'{"exact":"provider response"}', "application/json")
    return ProductDetailObservation(
        target=TARGET,
        endpoint_url=ENDPOINT_URL,
        request_fingerprint=REQUEST_FINGERPRINT,
        outcome="stored",
        observed_at=observed_at,
        response_receipt=receipt,
        content=content,
        http_status=200,
        error_code=None,
    )


def test_detail_response_decodes_korean_text_without_images() -> None:
    content = parse_detail_response(TARGET, _response())

    assert content is not None
    assert content.decoded_html == DETAIL_HTML
    assert content.detail_html_sha256 == sha256(DETAIL_HTML.encode()).hexdigest()
    expected = """
KN-PC200CPS, 주차주제어장치, 통합관리서버
물품식별번호:25044539
※ 통합관리서버
로컬에 설치된 기기 결제 관련 데이터를 통합하여 관리한다.
※ 제원
① CPU : 16Core 2.3Ghz
② RAM : 32GB
③ HDD : 1TB
""".strip()
    assert content.detail_text == expected
    assert "ignored-product-image" not in content.detail_text


def test_detail_response_distinguishes_missing_and_provider_error() -> None:
    assert parse_detail_response(TARGET, _response(None)) is None
    assert (
        parse_detail_response(
            TARGET,
            {
                "ErrorCode": 0,
                "ErrorMsg": "provider no-data message is not persisted",
                "dlGdsDtlInfoMngM": None,
            },
        )
        is None
    )

    with pytest.raises(ProductDetailResponseError, match="provider_error"):
        _ = parse_detail_response(
            TARGET,
            {
                "ErrorCode": "500",
                "ErrorMsg": "raw provider detail must not escape",
                "dlGdsDtlInfoMngM": {},
            },
        )


def test_store_appends_observations_and_advances_latest_pointer(
    tmp_path: Path,
) -> None:
    database = tmp_path / "priority.sqlite3"
    raw_store = RawBlobStore(tmp_path / "raw")
    _seed_product(database, TARGET)
    second = ProductDetailTarget(
        product_id="25044540",
        contract_item_management_number="0023H0531_1000000006",
        source_url=TARGET_URL.replace("0005", "0006"),
    )
    _seed_product(database, second)
    store = ProductDescriptionStore(database)

    assert store.pending_targets() == (TARGET, second)
    first_observation = _stored_observation(
        raw_store,
        "2026-07-31T01:00:00+00:00",
    )
    first_id = store.record(first_observation)
    second_id = store.record(
        _stored_observation(raw_store, "2026-07-31T02:00:00+00:00")
    )
    missing_receipt = raw_store.put(b'{"missing":true}', "application/json")
    _ = store.record(
        ProductDetailObservation(
            target=second,
            endpoint_url=ENDPOINT_URL,
            request_fingerprint=REQUEST_FINGERPRINT,
            outcome="missing",
            observed_at="2026-07-31T01:00:00+00:00",
            response_receipt=missing_receipt,
            content=None,
            http_status=200,
            error_code=None,
        )
    )

    assert second_id > first_id
    assert store.pending_targets() == ()
    assert store.pending_targets(retry_missing=True) == (second,)
    with sqlite3.connect(database) as connection:
        observation_count = query(
            connection,
            "SELECT COUNT(*) FROM priority_product_description_observations",
        ).fetchone()
        raw_count = query(
            connection,
            "SELECT COUNT(*) FROM raw_blobs",
        ).fetchone()
        target_state = query(
            connection,
            """
            SELECT latest_observation_id FROM priority_product_description_state
            WHERE product_id = ?
            """,
            (TARGET.product_id,),
        ).fetchone()
    assert observation_count is not None
    assert as_int(observation_count[0]) == 3
    assert raw_count is not None
    assert as_int(raw_count[0]) == 2
    assert target_state is not None
    assert as_int(target_state[0]) == second_id
    assert first_observation.response_receipt is not None
    assert (
        first_observation.response_receipt.body_sha
        in RawRetentionRepository(database).protected_body_shas()
    )


def test_failed_and_changed_targets_remain_pending(tmp_path: Path) -> None:
    database = tmp_path / "priority.sqlite3"
    raw_store = RawBlobStore(tmp_path / "raw")
    _seed_product(database, TARGET)
    store = ProductDescriptionStore(database)
    failed_id = store.record(
        ProductDetailObservation(
            target=TARGET,
            endpoint_url=ENDPOINT_URL,
            request_fingerprint=REQUEST_FINGERPRINT,
            outcome="failed",
            observed_at="2026-07-31T01:00:00+00:00",
            response_receipt=None,
            content=None,
            http_status=None,
            error_code="timeout",
        )
    )

    assert store.pending_targets() == (TARGET,)
    _ = store.record(
        _stored_observation(raw_store, "2026-07-31T02:00:00+00:00")
    )
    assert store.pending_targets() == ()
    changed_url = TARGET_URL.replace("0005", "0007")
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            "UPDATE priority_products SET detail_url = ? WHERE product_id = ?",
            (changed_url, TARGET.product_id),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="observations are immutable",
        ):
            _ = connection.execute(
                """
                UPDATE priority_product_description_observations
                SET observed_at = 'changed' WHERE id = ?
                """,
                (failed_id,),
            )
    assert store.pending_targets() == (
        ProductDetailTarget.from_product(TARGET.product_id, changed_url),
    )


@final
class _FakeDescriptionClient:
    def __init__(
        self,
        responses: Mapping[str, FetchedDescriptionResponse | Exception],
    ) -> None:
        self.responses = responses
        self.requested: list[str] = []

    async def fetch(
        self,
        target: ProductDetailTarget,
    ) -> FetchedDescriptionResponse:
        self.requested.append(target.product_id)
        response = self.responses[target.product_id]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_crawl_persists_stored_missing_and_retryable_failures(
    tmp_path: Path,
) -> None:
    database = tmp_path / "priority.sqlite3"
    raw_store = RawBlobStore(tmp_path / "raw")
    targets = tuple(
        ProductDetailTarget(
            product_id=str(25044539 + offset),
            contract_item_management_number=f"0023H0531_{1000000005 + offset}",
            source_url=(
                "https://shop.g2b.go.kr/link/GMSF001_01/"
                f"?ctrtItemMngNo=0023H0531_{1000000005 + offset}"
            ),
        )
        for offset in range(3)
    )
    for target in targets:
        _seed_product(database, target)
    client = _FakeDescriptionClient(
        {
            targets[0].product_id: FetchedDescriptionResponse(
                http_status=200,
                content_type="application/json;charset=UTF-8",
                body=json.dumps(_response(), ensure_ascii=False).encode(),
            ),
            targets[1].product_id: FetchedDescriptionResponse(
                http_status=200,
                content_type="application/json;charset=UTF-8",
                body=json.dumps(_response(None), ensure_ascii=False).encode(),
            ),
            targets[2].product_id: TimeoutError(),
        }
    )
    store = ProductDescriptionStore(database)

    summary = await crawl_product_descriptions(
        store,
        raw_store,
        client,
        targets,
        DescriptionCrawlOptions(
            concurrency=2,
            observed_at=lambda: "2026-07-31T03:00:00+00:00",
        ),
    )

    assert summary.stored == 1
    assert summary.missing == 1
    assert summary.failed == 1
    assert summary.abort_code is None
    assert store.outcome_counts() == {"failed": 1, "missing": 1, "stored": 1}


@pytest.mark.asyncio
async def test_systemic_contract_failure_stops_new_batches(
    tmp_path: Path,
) -> None:
    database = tmp_path / "priority.sqlite3"
    raw_store = RawBlobStore(tmp_path / "raw")
    targets = tuple(
        ProductDetailTarget(
            product_id=str(25044550 + offset),
            contract_item_management_number=f"0023H0531_{1000000016 + offset}",
            source_url=(
                "https://shop.g2b.go.kr/link/GMSF001_01/"
                f"?ctrtItemMngNo=0023H0531_{1000000016 + offset}"
            ),
        )
        for offset in range(3)
    )
    for target in targets:
        _seed_product(database, target)
    client = _FakeDescriptionClient(
        {
            targets[0].product_id: FetchedDescriptionResponse(
                200,
                "text/html",
                b"<html>login</html>",
            ),
            targets[1].product_id: FetchedDescriptionResponse(
                200,
                "application/json",
                b"{}",
            ),
            targets[2].product_id: FetchedDescriptionResponse(
                200,
                "application/json",
                b"{}",
            ),
        }
    )

    summary = await crawl_product_descriptions(
        ProductDescriptionStore(database),
        raw_store,
        client,
        targets,
        DescriptionCrawlOptions(
            concurrency=1,
            observed_at=lambda: "2026-07-31T03:00:00+00:00",
        ),
    )

    assert summary.abort_code == "session_invalid"
    assert summary.attempted == 1
    assert client.requested == [targets[0].product_id]


def test_request_fingerprint_pins_target_and_fixed_contract() -> None:
    same = description_request_fingerprint(TARGET)
    changed = description_request_fingerprint(
        ProductDetailTarget(
            product_id=TARGET.product_id,
            contract_item_management_number="changed",
            source_url=TARGET.source_url,
        )
    )

    assert len(same) == 64
    assert same == description_request_fingerprint(TARGET)
    assert changed != same
