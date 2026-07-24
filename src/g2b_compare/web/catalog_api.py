"""Read-only JSON catalog and child-option endpoints."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Literal, assert_never

from fastapi import APIRouter, HTTPException, Query

from g2b_compare.normalize.text import normalize_search_text
from g2b_compare.priority_attributes import parse_product_attributes
from g2b_compare.priority_catalog import (
    list_catalog_options,
    list_catalog_options_for_company,
    list_catalog_products,
)
from g2b_compare.priority_models import CatalogOption, CatalogProduct, PriorityLineSort

from .api_models import (
    CatalogAttributeResponse,
    CatalogOptionResponse,
    CatalogPageResponse,
    CatalogProductResponse,
)

if TYPE_CHECKING:
    from pathlib import Path


def build_catalog_api_router(database: Path) -> APIRouter:
    """Build catalog JSON routes backed by the existing priority catalog."""
    router = APIRouter()

    @router.get("/api/catalog/products", response_model=CatalogPageResponse)
    def products(
        q: Annotated[str, Query(max_length=500)] = "",
        company_name: Annotated[str, Query(max_length=200)] = "",
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> CatalogPageResponse:
        result = list_catalog_products(
            database,
            q,
            page=page,
            page_size=page_size,
            sort=sort,
            company_name=company_name,
        )
        items = [
            _product_response(item)
            for item in result.items
        ]
        return CatalogPageResponse(
            items=items,
            page=result.page,
            page_count=result.page_count,
            total_count=result.total_count,
        )

    @router.get(
        "/api/catalog/products/{product_id}/options",
        response_model=CatalogPageResponse,
    )
    def options(
        product_id: str,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 30,
        relation_kind: Annotated[
            Literal["additional", "component"] | None, Query()
        ] = None,
    ) -> CatalogPageResponse:
        if not _product_exists(database, product_id):
            raise HTTPException(status_code=404, detail="catalog product not found")
        all_options = tuple(
            item
            for item in list_catalog_options(database, product_id)
            if relation_kind is None or item.relation_kind == relation_kind
        )
        total = len(all_options)
        start = (page - 1) * page_size
        selected = all_options[start : start + page_size]
        items = [
            CatalogOptionResponse(
                parent_product_id=item.parent_product_id,
                relation_id=item.relation_id,
                relation_kind=item.relation_kind,
                product_id=item.product_id,
                name=item.item_name,
                spec=item.spec,
                unit=item.unit,
                price_won=item.price_won,
                company_name=item.company_name,
                detail_url=item.detail_url,
                g2b_url=item.detail_url,
                image_url=item.image_url,
                attributes=_option_attributes(database, item.product_id),
            )
            for item in selected
        ]
        return CatalogPageResponse(
            items=items,
            page=page,
            page_count=max(1, (total + page_size - 1) // page_size),
            total_count=total,
        )

    @router.get("/api/catalog/relations", response_model=CatalogPageResponse)
    def relations(  # noqa: PLR0913
        company_name: Annotated[str, Query(max_length=200)],
        category: Literal["selection", "additional", "construction"],
        q: Annotated[str, Query(max_length=500)] = "",
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 30,
    ) -> CatalogPageResponse:
        items = [
            item
            for item in _catalog_relations(database, company_name)
            if _relation_category(item) == category
        ]
        terms = tuple(normalize_search_text(q).split())
        if terms:
            items = [
                item
                for item in items
                if all(term in _document_text(item) for term in terms)
            ]
        items.sort(key=lambda item: _document_sort_key(item, sort))
        total = len(items)
        start = (page - 1) * page_size
        return CatalogPageResponse(
            items=items[start : start + page_size],
            page=page,
            page_count=max(1, (total + page_size - 1) // page_size),
            total_count=total,
        )

    @router.get(
        "/api/catalog/document-products",
        response_model=CatalogPageResponse,
    )
    def document_products(
        company_name: Annotated[str, Query(max_length=200)],
        q: Annotated[str, Query(max_length=500)] = "",
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> CatalogPageResponse:
        items = list(_document_catalog(database, company_name))
        terms = tuple(normalize_search_text(q).split())
        if terms:
            items = [
                item
                for item in items
                if all(term in _document_text(item) for term in terms)
            ]
        items.sort(key=lambda item: _document_sort_key(item, sort))
        total = len(items)
        start = (page - 1) * page_size
        return CatalogPageResponse(
            items=items[start : start + page_size],
            page=page,
            page_count=max(1, (total + page_size - 1) // page_size),
            total_count=total,
        )

    return router


def _document_catalog(
    database: Path,
    company_name: str,
) -> tuple[CatalogProductResponse | CatalogOptionResponse, ...]:
    return _cached_document_catalog(database.resolve(), company_name)


@lru_cache(maxsize=8)
def _cached_document_catalog(
    database: Path,
    company_name: str,
) -> tuple[CatalogProductResponse | CatalogOptionResponse, ...]:
    main_products = tuple(
        item
        for item in list_catalog_products(
            database,
            company_name,
            page=1,
            page_size=100_000,
            sort=PriorityLineSort.PRICE_ASC,
            company_name=company_name,
        ).items
        if item.company_name == company_name
    )
    options = list_catalog_options_for_company(database, company_name)
    option_attributes = _option_attributes_for_company(database, company_name)
    parent_names = {item.product_id: item.item_name for item in main_products}
    return (
        *(_product_response(item) for item in main_products),
        *(
            _option_response(
                item,
                option_attributes.get(item.product_id, []),
                parent_names.get(item.parent_product_id, ""),
            )
            for item in options
        ),
    )


@lru_cache(maxsize=8)
def _catalog_relations(
    database: Path,
    company_name: str,
) -> tuple[CatalogOptionResponse, ...]:
    options = list_catalog_options_for_company(database, company_name)
    parent_ids = tuple({item.parent_product_id for item in options})
    parent_names: dict[str, str] = {}
    if parent_ids:
        placeholders = ",".join("?" for _ in parent_ids)
        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                f"SELECT product_id, category_name FROM priority_products "  # noqa: S608
                f"WHERE product_id IN ({placeholders})",
                parent_ids,
            ).fetchall()
        parent_names = {str(row[0]): str(row[1] or "") for row in rows}
    option_attributes = _option_attributes_for_company(database, company_name)
    return tuple(
        _option_response(
            item,
            option_attributes.get(item.product_id, []),
            parent_names.get(item.parent_product_id, ""),
        )
        for item in options
    )


def _product_response(item: CatalogProduct) -> CatalogProductResponse:
    return CatalogProductResponse(
        product_id=item.product_id,
        name=item.item_name,
        spec=item.spec,
        unit=item.unit,
        price_won=item.price_won,
        company_name=item.company_name,
        contract_method=item.contract_method,
        delivery_condition=item.delivery_condition,
        delivery_days=item.delivery_days,
        contract_end_date=item.contract_end_date,
        detail_url=item.detail_url,
        g2b_url=item.detail_url,
        image_url=item.image_url,
        attributes=[
            CatalogAttributeResponse.model_validate(attribute.model_dump())
            for attribute in item.attributes
        ],
    )


def _option_response(
    item: CatalogOption,
    attributes: list[CatalogAttributeResponse],
    parent_name: str,
) -> CatalogOptionResponse:
    return CatalogOptionResponse(
        parent_product_id=item.parent_product_id,
        parent_name=parent_name,
        relation_id=item.relation_id,
        relation_kind=item.relation_kind,
        product_id=item.product_id,
        name=item.item_name,
        spec=item.spec,
        unit=item.unit,
        price_won=item.price_won,
        company_name=item.company_name,
        detail_url=item.detail_url,
        g2b_url=item.detail_url,
        image_url=item.image_url,
        attributes=attributes,
    )


def _document_text(
    item: CatalogProductResponse | CatalogOptionResponse,
) -> str:
    attributes = " ".join(
        f"{attribute.name} {attribute.value} {attribute.unit}"
        for attribute in item.attributes
    )
    return normalize_search_text(
        f"{item.name} {item.spec} {item.product_id} {item.company_name} {attributes}"
    )


def _document_sort_key(
    item: CatalogProductResponse | CatalogOptionResponse,
    sort: PriorityLineSort,
) -> tuple[int | str, ...]:
    relation_id = item.relation_id if isinstance(item, CatalogOptionResponse) else ""
    match sort:
        case PriorityLineSort.PRICE_ASC:
            return (item.price_won, item.name.casefold(), item.product_id, relation_id)
        case PriorityLineSort.PRICE_DESC:
            return (-item.price_won, item.name.casefold(), item.product_id, relation_id)
        case PriorityLineSort.NAME_ASC:
            return (item.name.casefold(), item.product_id, relation_id)
        case PriorityLineSort.PRODUCT_ID_ASC:
            return (item.product_id, item.name.casefold(), relation_id)
        case unreachable:
            assert_never(unreachable)


def _relation_category(item: CatalogOptionResponse) -> str:
    if "공사" in f"{item.name} {item.spec}":
        return "construction"
    return "selection" if item.relation_kind == "component" else "additional"


def _product_exists(database: Path, product_id: str) -> bool:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT 1 FROM priority_products WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
    return row is not None


def _option_attributes(
    database: Path, product_id: str
) -> list[CatalogAttributeResponse]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT raw_json FROM priority_products WHERE product_id = ? LIMIT 1",
            (product_id,),
        ).fetchone()
    if not row or not row[0]:
        return []
    return [
        CatalogAttributeResponse.model_validate(attribute.model_dump())
        for attribute in parse_product_attributes(str(row[0]))
    ]


def _option_attributes_for_company(
    database: Path,
    company_name: str,
) -> dict[str, list[CatalogAttributeResponse]]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT product.product_id, product.raw_json
            FROM priority_products AS product
            WHERE product.product_id IN (
                SELECT option_product_id
                FROM priority_contract_options
                WHERE company_name = ? AND active = 1
                UNION
                SELECT option_product_id
                FROM verified_product_options
                WHERE company_name = ? AND active = 1
            )
            """,
            (company_name, company_name),
        ).fetchall()
    return {
        str(row[0]): [
            CatalogAttributeResponse.model_validate(attribute.model_dump())
            for attribute in parse_product_attributes(str(row[1]))
        ]
        for row in rows
        if row[1]
    }
