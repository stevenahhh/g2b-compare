"""Local priority-catalog search route for the integrated MVP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from g2b_compare.priority_models import PriorityLineSort
from g2b_compare.priority_store import PriorityStore

if TYPE_CHECKING:
    from pathlib import Path

    from jinja2 import Environment


def build_catalog_router(database: Path, templates: Environment) -> APIRouter:
    """Serve 30-row searches from the shared priority catalog."""
    store = PriorityStore(database)
    router = APIRouter()

    def catalog(  # noqa: PLR0913
        q: Annotated[str, Query(max_length=500)] = "",
        product_name: Annotated[str, Query(max_length=100)] = "",
        spec_text: Annotated[str, Query(max_length=500)] = "",
        estimate_id: Annotated[str, Query(max_length=64)] = "",
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        search = q or " ".join(value for value in (product_name, spec_text) if value)
        result = store.list_catalog_products(search, page=page, page_size=30, sort=sort)
        params = {
            "q": search,
            "estimate_id": estimate_id,
            "sort": sort.value,
        }
        html = templates.get_template("catalog.html").render(
            query=search,
            estimate_id=estimate_id,
            sort=sort,
            result=result,
            previous_url=_page_url(params, page - 1) if page > 1 else None,
            next_url=(
                _page_url(params, page + 1) if page < result.page_count else None
            ),
        )
        return HTMLResponse(html)

    def catalog_items(  # noqa: PLR0913
        q: Annotated[str, Query(max_length=500)] = "",
        product_name: Annotated[str, Query(max_length=100)] = "",
        spec_text: Annotated[str, Query(max_length=500)] = "",
        estimate_id: Annotated[str, Query(max_length=64)] = "",
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        search = q or " ".join(value for value in (product_name, spec_text) if value)
        result = store.list_catalog_products(search, page=page, page_size=30, sort=sort)
        html = templates.get_template("_catalog_items.html").render(
            result=result,
            show_empty=False,
            estimate_id=estimate_id,
        )
        next_page = str(page + 1) if page < result.page_count else ""
        return HTMLResponse(html, headers={"X-Catalog-Next-Page": next_page})

    def catalog_options(
        product_id: str,
        estimate_id: Annotated[str, Query(max_length=64)] = "",
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        all_options = store.list_catalog_options(product_id)
        offset = (page - 1) * 30
        options = all_options[offset : offset + 30]
        next_page = str(page + 1) if offset + 30 < len(all_options) else ""
        html = templates.get_template("_catalog_options.html").render(
            parent_product_id=product_id,
            options=options,
            total_count=len(all_options),
            estimate_id=estimate_id,
            fragment=page > 1,
        )
        return HTMLResponse(
            html,
            headers={"X-Catalog-Options-Next-Page": next_page},
        )

    router.add_api_route("/", catalog, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route(
        "/catalog/items",
        catalog_items,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    router.add_api_route(
        "/catalog/products/{product_id}/options",
        catalog_options,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    return router


def _page_url(params: dict[str, str], page: int) -> str:
    return f"/?{urlencode({**params, 'page': str(page)})}"
