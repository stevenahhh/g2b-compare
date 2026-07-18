"""Typed production-path fixtures for Todo 13."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, override

import httpx

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparator_models import (
    CuratedRelation,
    ObservedOptionRole,
    ProductRecord,
)
from g2b_compare.services.release_models import ReleaseContractError, ReleasePin
from g2b_compare.services.search_models import CategoryRef, SearchReader
from g2b_compare.web.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.services.comparators import ComparatorView

NO_READY_RELEASE = "no_ready_release"
FATAL_RELEASE = "corrupt_release"


def release_pin() -> ReleasePin:
    return ReleasePin(
        1,
        1,
        1,
        1,
        1,
        "ranking-v1",
        "normalization-v1",
        "materialization-v1",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "2026-07-17T00:00:00+00:00",
    )


def product(
    number: int,
    *,
    category: tuple[str, str] = ("10", "1001"),
    unit: str | None = "개",
    option: str = "렌즈 4 mm",
    coverage: str = "1/1",
) -> ProductRecord:
    price = ComparisonPrice(
        active=unit is not None,
        amount_won=None if unit is None else 100_000 + number,
        unit_key=unit,
        offer_key=None,
        reason="missing-unit" if unit is None else None,
    )
    return ProductRecord(
        RankableProduct(
            f"P{number:03}",
            category,
            "cctv",
            option,
            active=True,
            price=price,
        ),
        "CCTV",
        "2026-07-17",
        coverage,
    )


def observed_product(number: int) -> ProductRecord:
    role = ObservedOptionRole(1, "row", "delivery", "1", "0", "추가", "2026-07-17")
    return replace(product(number), observed_option_roles=(role,))


def curated_product(number: int) -> ProductRecord:
    relation = CuratedRelation("r", "p", "c", "workbook", "a" * 64, "내역", 2)
    return replace(product(number), curated_relations=(relation,))


def named_product(number: int, raw_name: str) -> ProductRecord:
    return replace(product(number), product_name_raw=raw_name)


@dataclass(slots=True)
class FixtureReader(SearchReader):
    products: tuple[ProductRecord, ...]
    categories_value: tuple[CategoryRef, ...] = (CategoryRef("10", "1001"),)
    statuses: tuple[str, ...] = ()
    pin_error: str | None = None
    stale_service: bool = False

    @override
    def pin_active_release(self) -> ReleasePin:
        if self.pin_error is not None:
            raise ReleaseContractError(self.pin_error)
        return release_pin()

    @override
    def is_stale(self, pin: ReleasePin) -> bool:
        return self.stale_service

    @override
    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        return self.categories_value

    @override
    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        return self.products

    @override
    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        return None

    def web_statuses(self, _release: ReleasePin) -> tuple[str, ...]:
        return self.statuses


def reader(
    count: int = 4,
    **changes: object,
) -> FixtureReader:
    base = FixtureReader(tuple(product(index) for index in range(count)))
    return replace(base, **changes)


async def get(
    fixture: SearchReader,
    path: str = "/?product_name=CCTV",
    *,
    enhanced: bool = False,
    link_manifest: Path | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(
        app=create_app(fixture, link_manifest=link_manifest)
    )
    headers = {"X-Requested-With": "fetch"} if enhanced else None
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.get(path, headers=headers)


def state(response: httpx.Response) -> str:
    marker = 'data-primary-state="'
    return response.text.split(marker, 1)[1].split('"', 1)[0]


def status_tokens(response: httpx.Response) -> set[str]:
    marker = 'data-statuses="'
    value = response.text.split(marker, 1)[1].split('"', 1)[0]
    return set(value.split())
