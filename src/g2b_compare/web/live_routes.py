"""Serve one no-accumulation search resolved directly against the live API."""

from __future__ import annotations

from dataclasses import replace
from decimal import InvalidOperation
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import (
    SearchResponse,
    SearchResult,
    SearchServiceError,
)
from g2b_compare.sources.envelope import MalformedEnvelopeError, ProviderStatusError
from g2b_compare.sources.transport import (
    AuthenticationTransportError,
    ContentTypeTransportError,
    ContractTransportError,
    RetryableTransportError,
)

from .live_reader import WebLiveSearchReader
from .navigation import add_pagination
from .rendering import (
    STATE_COPY,
    VALIDATION_COPY,
    is_enhanced_request,
    parse_search_request,
    render_response,
    search_error_response,
)
from .state import parse_statuses, sanitize_statuses
from .viewmodels import search_view

if TYPE_CHECKING:
    from jinja2 import Environment

    from g2b_compare.sources.shopping_mall import ShoppingMallAdapter

    from .types import ViewValue

RESULTS_PATH: Final = "/live"
LIVE_RESULTS_MESSAGE: Final = "실시간 조회 결과"
LIVE_PAGE_SIZE: Final = 30
LIVE_FAILURE_MESSAGE: Final = "실시간 조회에 실패했습니다. 잠시 후 다시 시도하세요"
MISSING_KEY_MESSAGE: Final = (
    "서비스 키가 설정되지 않았습니다 — .env에 G2B_SERVICE_KEY를 설정하세요"
)
_LIVE_FETCH_ERRORS: Final = (
    AuthenticationTransportError,
    ContractTransportError,
    ContentTypeTransportError,
    RetryableTransportError,
    MalformedEnvelopeError,
    ProviderStatusError,
)
_LIVE_SORTS: Final = frozenset({"official", "recent", "price_asc", "price_desc"})


def build_live_router(
    adapter: ShoppingMallAdapter,
    service_key: str,
    templates: Environment,
) -> APIRouter:
    """Bind the live-search dependencies to their own dedicated route."""
    router = APIRouter()

    def endpoint(request: Request) -> HTMLResponse | JSONResponse:
        return _live_index(request, adapter, service_key, templates)

    router.add_api_route(
        RESULTS_PATH,
        endpoint,
        methods=["GET"],
        response_class=HTMLResponse,
        response_model=None,
    )
    return router


def _live_index(
    request: Request,
    adapter: ShoppingMallAdapter,
    service_key: str,
    templates: Environment,
) -> HTMLResponse | JSONResponse:
    query = request.query_params
    submitted = "product_name" in query
    base: dict[str, ViewValue] = {
        "request": request,
        "form": dict(query),
        "submitted": submitted,
        "primary_state": "initial",
        "statuses": [],
        "message": STATE_COPY["initial"],
        "rows": [],
        "form_action": RESULTS_PATH,
        "live_mode": True,
    }
    if not submitted:
        return render_response(request, templates, base, 200)
    if not service_key:
        view = {
            **base,
            "primary_state": "fatal-error",
            "message": MISSING_KEY_MESSAGE,
        }
        return render_response(request, templates, view, 503)
    try:
        validated_request = parse_search_request(dict(query))
    except (ValidationError, ValueError, InvalidOperation):
        return render_response(
            request,
            templates,
            {
                **base,
                "primary_state": "validation-error",
                "message": VALIDATION_COPY,
                "field_error": VALIDATION_COPY,
            },
            422 if is_enhanced_request(request) else 200,
        )
    source_page = validated_request.page
    search_request = validated_request.model_copy(update={"page": 1})
    reader = WebLiveSearchReader(
        search_request.product_name,
        adapter,
        service_key,
        source_page=source_page,
    )
    try:
        result = execute_search(search_request, reader)
        selected_sort = _selected_sort(query.get("sort"))
        result = _sort_live_response(result, reader.product_order, selected_sort)
        view = {
            **base,
            **search_view(result, {}, tuple(request.query_params.multi_items())),
        }
        statuses = parse_statuses(view["statuses"])
        view["statuses"] = sanitize_statuses(statuses)
        view["page"] = source_page
        view["page_size"] = LIVE_PAGE_SIZE
        view["result_count"] = len(result.results)
        view["selected_sort"] = selected_sort
        if view["primary_state"] == "current-results":
            view["message"] = LIVE_RESULTS_MESSAGE
        else:
            view["message"] = STATE_COPY[str(view["primary_state"])]
        add_pagination(
            view,
            list(request.query_params.multi_items()),
            RESULTS_PATH,
            page_size=LIVE_PAGE_SIZE,
            has_next=reader.has_next,
        )
        return render_response(request, templates, view, 200)
    except SearchServiceError as error:
        return search_error_response(
            request, templates, base, error, results_path=RESULTS_PATH
        )
    except _LIVE_FETCH_ERRORS:
        view = {
            **base,
            "primary_state": "fatal-error",
            "message": LIVE_FAILURE_MESSAGE,
            "request_id": uuid4().hex,
        }
        return render_response(request, templates, view, 500)


def _selected_sort(raw: str | None) -> str:
    return raw if raw in _LIVE_SORTS else "official"


def _sort_live_response(
    response: SearchResponse,
    product_order: tuple[str, ...],
    selected_sort: str,
) -> SearchResponse:
    order = {product_id: index for index, product_id in enumerate(product_order)}
    match selected_sort:
        case "price_asc":
            rows = sorted(response.results, key=_ascending_price_key)
        case "price_desc":
            rows = sorted(response.results, key=_descending_price_key)
        case "recent":
            rows = sorted(response.results, key=_recent_key)
        case _:
            rows = sorted(
                response.results,
                key=lambda item: order.get(
                    item.product.rankable.product_id, len(order)
                ),
            )
    return replace(response, results=tuple(rows))


def _ascending_price_key(item: SearchResult) -> tuple[bool, int]:
    price = item.product.rankable.price.amount_won
    return price is None, 0 if price is None else price


def _descending_price_key(item: SearchResult) -> tuple[bool, int]:
    missing, amount = _ascending_price_key(item)
    return missing, -amount


def _recent_key(item: SearchResult) -> tuple[int, bytes]:
    raw = item.product.data_as_of
    digits = "".join(character for character in raw if character.isdigit())
    timestamp = int(digits[:14] or "0")
    return -timestamp, item.product.rankable.product_id.encode()
