from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from openpyxl import Workbook

from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_models import PriorityDataset, ProductOptionRelation
from g2b_compare.priority_site import parse_option_label
from g2b_compare.priority_store import PriorityStore
from g2b_compare.priority_workbook import read_priority_workbook
from g2b_compare.sources.shopping_mall import (
    CatalogRecord,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)

if TYPE_CHECKING:
    from pathlib import Path

    from openpyxl.worksheet.worksheet import Worksheet

    from g2b_compare.contracts.redact import JsonValue


def _workbook(path: Path) -> None:
    book = Workbook()
    companies = book.active
    assert companies is not None
    companies.title = "업체소재별현황"
    companies.append([])
    companies.append([])
    companies.append([])
    companies.append([])
    companies.append(
        ["No", "계약업체", "본사소재지", "기업구분", "상품수", "계약종료일"]
    )
    companies.append([1, "주식회사 홍석", "전남", "중소기업", 2, "2026-11-07"])

    options = cast("Worksheet", book.create_sheet("우수옵션"))
    options.append([])
    options.append(
        ["업체명", "구분", "조달식별번호", "품명", "규격", "금액", "기타상세"]
    )
    options.append(
        ["주식회사 홍석", "추가선택", "22066119", "카메라브래킷", "벽부형", 84960, ""]
    )
    options.append(
        [
            "주식회사 홍석",
            "추가선택",
            "22066119",
            "카메라브래킷",
            "천장형",
            94960,
            "중복 ID 원본",
        ]
    )
    options.append(
        ["주식회사 홍석", "선택부품", "22801 41", "원본오류품목", "", 0, "원문 보존"]
    )
    book.save(path)


def _record() -> CatalogRecord:
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    raw: dict[str, JsonValue] = {
        "shopngCntrctNo": "0023H041705",
        "shopngCntrctSno": "4",
        "prdctIdntNo": "25093743",
        "prdctClsfcNo": "46171622",
        "prdctClsfcNoNm": "영상감시장치",
        "dtilPrdctClsfcNo": "4617162201",
        "prdctSpecNm": "영상감시장치, 리더캠, LDC-02-3C",
        "cntrctPrceAmt": "2100000",
        "prdctImgUrl": "https://shop.g2b.go.kr/product.jpg",
        "cntrctCorpNm": "주식회사 리더캠",
        "prdctUnit": "조",
        "cntrctMthdNm": "다수공급자계약",
        "prdctDlvryCndtnNm": "납품장소도",
        "dlvrTmlmtDaynum": "60",
        "cntrctEndDate": "20261109",
    }
    return CatalogRecord(
        identity=SourceIdentity(operation, ("0023H041705", "4")),
        product_id="25093743",
        classification_number="46171622",
        category_name="영상감시장치",
        detail_category_number="4617162201",
        spec_name="영상감시장치, 리더캠, LDC-02-3C",
        contract_price="2100000",
        image_url="https://shop.g2b.go.kr/product.jpg",
        timestamp=TimestampEvidence(
            "20260721", TimestampOrigin.OBSERVED_AT_FALLBACK, 0
        ),
        raw_fields=raw,
    )


def test_priority_workbook_preserves_every_source_option_row(tmp_path: Path) -> None:
    path = tmp_path / "priority.xlsm"
    _workbook(path)

    dataset = read_priority_workbook(path)

    assert isinstance(dataset, PriorityDataset)
    assert len(dataset.companies) == 1
    assert len(dataset.options) == 3
    assert dataset.options[0].source_row == 3
    assert dataset.options[1].source_row == 4
    assert dataset.options[0].product_id == dataset.options[1].product_id
    assert dataset.options[2].product_id == "22801 41"


def test_store_keeps_imported_rows_product_and_parent_option_relation(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "priority.xlsm"
    database = tmp_path / "priority.sqlite3"
    _workbook(workbook)
    store = PriorityStore(database)
    store.replace_dataset(read_priority_workbook(workbook))
    store.save_catalog_page(
        company_name="주식회사 홍석",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=1000,
        total_count=1,
        records=(_record(),),
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    )
    store.save_site_result(
        "25093743",
        (
            ProductOptionRelation(
                kind="additional",
                product_id="22066119",
                raw_label="[별도구매] [22066119] 카메라브래킷 : 84,960",
                price_won=84960,
            ),
        ),
        status="complete",
    )

    status = store.status()
    rows = store.list_lines("", page=1, page_size=30)

    assert status.company_count == 1
    assert status.option_row_count == 3
    assert status.unique_option_count == 2
    assert status.product_count == 1
    assert status.relation_count == 1
    assert status.pending_api_target_count == 2
    assert any(row.path == "본품 [25093743]" for row in rows.items)
    assert next(
        row.detail_url for row in rows.items if row.path == "본품 [25093743]"
    ).endswith("ctrtItemMngNo=0023H0417_1050000004")
    relation = next(
        row for row in rows.items if row.path == "본품 [25093743] > 옵션 [22066119]"
    )
    assert relation.relation_id is not None

    store.save_site_result("25093743", (), status="retry")

    assert store.status().pending_site_product_count == 1


def test_option_label_parser_extracts_id_and_price() -> None:
    assert parse_option_label(
        "[별도구매] [설치비] [22066417] 정보통신공사, 카메라 설치 : 27,930"
    ) == (
        "22066417",
        "[별도구매] [설치비] [22066417] 정보통신공사, 카메라 설치 : 27,930",
        27930,
    )
    assert parse_option_label("추가할 상품을 선택하세요") is None
