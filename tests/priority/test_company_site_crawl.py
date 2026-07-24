from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

from g2b_compare.company_site_crawl import (
    crawl_company_site_products,
)
from g2b_compare.priority_models import PriorityCompany, PriorityDataset
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_site import ShoppingSitePage, SiteRow

if TYPE_CHECKING:
    from pathlib import Path


class _Adapter:
    def fetch(self, company_name: str, page_number: int) -> ShoppingSitePage:
        assert company_name == "업체 A"
        rows = (
            _row("00000001", "CONTRACT-1", 1000),
            _row("00000001", "CONTRACT-2", 1200),
        )
        if page_number == 2:
            rows = (_row("00000002", "CONTRACT-3", 2000),)
        return ShoppingSitePage(rows=rows, page_number=page_number, total_count=101)


class _SameNameAdapter:
    def fetch(self, company_name: str, page_number: int) -> ShoppingSitePage:
        assert company_name == "주식회사 새움"
        assert page_number == 1
        target = _row("11111111", "TARGET-1", 1000)
        target.update(
            {
                "ctentUntyGrpNm": "주식회사 새움",
                "bzmnRegNo": "2158717690",
                "addr": "경기도 하남시 미사대로 540",
            }
        )
        other = _row("25410424", "OTHER-1", 23000)
        other.update(
            {
                "ctentUntyGrpNm": "주식회사 새움",
                "bzmnRegNo": "4518602777",
                "addr": "경상북도 예천군 예천읍 도립대학길 114",
            }
        )
        return ShoppingSitePage(
            rows=(target, other),
            page_number=1,
            total_count=2,
        )


def test_site_crawl_keeps_every_offer_and_deduplicates_main_products(
    tmp_path: Path,
) -> None:
    store = PriorityStore(tmp_path / "priority.sqlite3")
    store.replace_dataset(
        PriorityDataset(
            companies=(
                PriorityCompany(
                    source_row=1,
                    name="업체 A",
                    location="서울",
                    company_type="일반",
                    declared_product_count=2,
                    contract_end_date="2027-12-31",
                ),
            ),
            options=(),
        )
    )

    result = crawl_company_site_products(store, _Adapter(), workers=1)

    assert result.calls == 2
    assert result.accepted_rows == 3
    assert result.quarantined_rows == 0
    assert result.failures == 0
    assert result.remaining_targets == 0
    with sqlite3.connect(store.database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM priority_products"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM priority_product_offers WHERE active = 1"
        ).fetchone() == (3,)
        product = cast(
            "tuple[str, str, str, str] | None",
            connection.execute(
                """
                SELECT company_name, spec, image_url, detail_url
                FROM priority_products WHERE product_id = '00000001'
                """
            ).fetchone(),
        )
    assert product == (
        "업체 A",
        "품명, 업체 A, 규격 (본품)",
        "https://shop.g2b.go.kr/image/00000001.jpg",
        "https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo=CONTRACT-2",
    )


def test_site_crawl_rejects_same_name_company_at_another_location(
    tmp_path: Path,
) -> None:
    store = PriorityStore(tmp_path / "priority.sqlite3")
    store.replace_dataset(
        PriorityDataset(
            companies=(
                PriorityCompany(
                    source_row=1,
                    name="주식회사 새움",
                    location="경기도 하남시",
                    company_type="중소기업",
                    declared_product_count=1,
                    contract_end_date="2026-07-30",
                ),
            ),
            options=(),
        )
    )

    result = crawl_company_site_products(store, _SameNameAdapter(), workers=1)

    assert result.accepted_rows == 1
    with sqlite3.connect(store.database) as connection:
        product_ids = connection.execute(
            "SELECT product_id FROM priority_products ORDER BY product_id"
        ).fetchall()
    assert product_ids == [("11111111",)]


def _row(
    product_id: str,
    contract_item: str,
    price: int,
) -> SiteRow:
    return {
        "ctrtItemMngNo": contract_item,
        "ctrtItemSqno": "1",
        "itemIdnfNo": product_id,
        "itemClsfNo": "10000000",
        "itemCfnm": "품명",
        "dtlsPrnmNo": "1000000001",
        "itemIdnfNm": "품명, 업체 A, 규격 &#40;본품&#41;",
        "ctrtUprc": price,
        "sImgSrc": f"/image/{product_id}.jpg",
        "ctrtYmd": "20260721",
        "ctentUntyGrpNm": "업체 A",
        "bzmnRegNo": "1234567890",
        "addr": "서울특별시 중구",
        "ctrtUntVal": "개",
        "shopCtrtTyNm": "다수공급자계약",
        "devyCndtNm": "현장설치도",
        "dlvgdsTermNody": "30",
        "ctrtEndYmd": "20271231",
    }
