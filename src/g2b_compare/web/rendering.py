"""Reader-agnostic request parsing and response shaping shared by every search route."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi.responses import HTMLResponse, JSONResponse

from g2b_compare.services.search_models import SearchRequest, SearchServiceError

from .navigation import category_choices

if TYPE_CHECKING:
    from fastapi import Request
    from jinja2 import Environment

    from .types import ViewValue

VALIDATION_COPY = "검색 조건을 확인하세요"
STATE_COPY = {
    "initial": "검색 조건을 입력하세요",
    "no-active-snapshot": "검색 데이터가 아직 준비되지 않았습니다",
    "no-matches": "정확히 일치하는 물품이 없습니다",
    "current-results": "현재 로컬 데이터 기준 결과",
    "stale": "데이터가 오래되었습니다",
    "sync-failed-last-good": "최근 동기화에 실패하여 이전 데이터를 표시합니다",
    "fatal-error": "검색을 처리할 수 없습니다",
}


def is_enhanced_request(request: Request) -> bool:
    """Detect the fetch-driven partial response variant."""
    return request.headers.get("x-requested-with") == "fetch"


def parse_search_request(query: dict[str, str]) -> SearchRequest:
    """Validate the strict public search request from raw query fields."""
    target = query.get("target_price_won", "")
    tolerance = query.get("price_tolerance_pct", "")
    page = query.get("page", "1")
    return SearchRequest.model_validate(
        {
            "product_name": query.get("product_name", ""),
            "category_code": query.get("category_code") or None,
            "detail_category_code": query.get("detail_category_code") or None,
            "spec_text": query.get("spec_text", ""),
            "spec_filter": query.get("spec_filter", ""),
            "target_price_won": None if not target else int(target),
            "price_unit": query.get("price_unit") or None,
            "price_tolerance_pct": None if not tolerance else Decimal(tolerance),
            "page": int(page),
            "page_size": 50,
        }
    )


def search_error_response(
    request: Request,
    templates: Environment,
    base: dict[str, ViewValue],
    error: SearchServiceError,
    *,
    results_path: str,
) -> HTMLResponse | JSONResponse:
    """Project one semantic search error into its exact response shape."""
    if error.code == "stale_snapshot":
        view = {
            **base,
            "primary_state": "stale",
            "statuses": ["stale"],
            "message": STATE_COPY["stale"],
        }
        return render_response(request, templates, view, 200)
    if error.code in {"ambiguous_category", "ambiguous_detail_category"}:
        choices = tuple(error.choices)
        view = {
            **base,
            "primary_state": "validation-error",
            "message": VALIDATION_COPY,
            "choices": category_choices(
                base["form"], choices, results_path=results_path
            ),
            "choice_values": choices,
            "response_kind": "category-choice",
        }
        status = 422 if is_enhanced_request(request) else 200
        return render_response(request, templates, view, status)
    if error.code == "invalid_spec_filter":
        view = {
            **base,
            "primary_state": "validation-error",
            "message": "스펙 필터를 해석할 수 없습니다",
            "field_error": "예: 800만화소, 500GB 이상",
        }
        status = 422 if is_enhanced_request(request) else 200
        return render_response(request, templates, view, status)
    view = {
        **base,
        "primary_state": "validation-error",
        "message": VALIDATION_COPY,
        "field_error": VALIDATION_COPY,
    }
    status = 422 if is_enhanced_request(request) else 200
    return render_response(request, templates, view, status)


def render_response(
    request: Request,
    templates: Environment,
    view: dict[str, ViewValue],
    status: int,
) -> HTMLResponse | JSONResponse:
    """Return the fetch-partial JSON envelope or a full HTML page."""
    if is_enhanced_request(request):
        html = render(templates, "results.html", view)
        payload = {
            "html": html,
            "primary_state": view["primary_state"],
            "kind": view.get("response_kind", "results"),
            "choices": view.get("choice_values", []),
        }
        return JSONResponse(payload, status)
    return render_template(templates, "index.html", view, status)


def render_template(
    templates: Environment,
    name: str,
    view: dict[str, ViewValue],
    status: int,
) -> HTMLResponse:
    """Render one full-page template into an HTML response."""
    return HTMLResponse(render(templates, name, view), status)


def render(
    templates: Environment,
    name: str,
    view: dict[str, ViewValue],
) -> str:
    """Render one named template against the escaped view mapping."""
    template = templates.get_template(name)
    return template.render(**view)
