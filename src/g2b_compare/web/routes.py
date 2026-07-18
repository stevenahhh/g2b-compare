"""Serve SSR GET searches and equivalent enhanced responses."""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from g2b_compare.services.release_models import ReleaseContractError
from g2b_compare.services.release_reader import NO_READY_RELEASE
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import (
    SearchReader,
    SearchRequest,
    SearchServiceError,
)

from .navigation import add_pagination, category_choices
from .state import parse_statuses, result_state, sanitize_statuses
from .viewmodels import search_view

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jinja2 import Environment

    from g2b_compare.services.release_models import ReleasePin

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


@runtime_checkable
class SearchStatusReader(Protocol):
    """Expose optional persisted UI status signals."""

    def web_statuses(self, release: ReleasePin) -> tuple[str, ...]:
        """Return persisted sync/freshness status without network access."""
        ...


def build_router(
    reader: SearchReader,
    templates: Environment,
    link_manifests: Mapping[str, Mapping[str, ViewValue]],
) -> APIRouter:
    """Bind typed application dependencies to the HTTP route."""
    router = APIRouter()

    def endpoint(request: Request) -> HTMLResponse | JSONResponse:
        return _index(request, reader, templates, link_manifests)

    router.add_api_route(
        "/",
        endpoint,
        methods=["GET"],
        response_class=HTMLResponse,
        response_model=None,
    )
    return router


def _index(
    request: Request,
    reader: SearchReader,
    templates: Environment,
    link_manifests: Mapping[str, Mapping[str, ViewValue]],
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
    }
    if not submitted:
        return _initial_response(request, reader, templates, base)
    try:
        search_request = _parse_request(dict(query))
    except (ValidationError, ValueError, InvalidOperation):
        return _response(
            request,
            templates,
            {
                **base,
                "primary_state": "validation-error",
                "message": VALIDATION_COPY,
                "field_error": VALIDATION_COPY,
            },
            422 if _enhanced(request) else 200,
        )
    try:
        result = execute_search(search_request, reader)
        view = {**base, **search_view(result, link_manifests)}
        external = (
            reader.web_statuses(result.release)
            if isinstance(reader, SearchStatusReader)
            else ()
        )
        local_statuses = parse_statuses(view["statuses"])
        statuses = sanitize_statuses((*local_statuses, *external))
        view["statuses"] = statuses
        primary_state = result_state(str(view["primary_state"]), statuses)
        view["primary_state"] = primary_state
        view["message"] = STATE_COPY[primary_state]
        add_pagination(view, list(request.query_params.multi_items()))
        return _response(request, templates, view, 200)
    except SearchServiceError as error:
        return _search_error_response(request, templates, base, error)
    except ReleaseContractError as error:
        return _release_error_response(request, templates, base, error)
    except sqlite3.OperationalError:
        return _release_error_response(
            request,
            templates,
            base,
            ReleaseContractError(NO_READY_RELEASE),
        )


def _initial_response(
    request: Request,
    reader: SearchReader,
    templates: Environment,
    base: dict[str, ViewValue],
) -> HTMLResponse | JSONResponse:
    try:
        release = reader.pin_active_release()
        external = (
            reader.web_statuses(release)
            if isinstance(reader, SearchStatusReader)
            else ()
        )
        statuses = [*external]
        if reader.is_stale(release):
            statuses.append("stale")
        base["statuses"] = sanitize_statuses(statuses)
        return _response(request, templates, base, 200)
    except ReleaseContractError as error:
        return _release_error_response(request, templates, base, error)
    except sqlite3.OperationalError:
        return _release_error_response(
            request,
            templates,
            base,
            ReleaseContractError(NO_READY_RELEASE),
        )


def _release_error_response(
    request: Request,
    templates: Environment,
    base: dict[str, ViewValue],
    error: ReleaseContractError,
) -> HTMLResponse | JSONResponse:
    if error.code in {NO_READY_RELEASE, "no_ready_release"}:
        state, status = "no-active-snapshot", 503
        view = {**base, "primary_state": state, "message": STATE_COPY[state]}
    else:
        state, status = "fatal-error", 500
        view = {
            **base,
            "primary_state": state,
            "message": STATE_COPY[state],
            "request_id": uuid4().hex,
        }
    return _response(request, templates, view, status)


def _search_error_response(
    request: Request,
    templates: Environment,
    base: dict[str, ViewValue],
    error: SearchServiceError,
) -> HTMLResponse | JSONResponse:
    if error.code == "stale_snapshot":
        view = {
            **base,
            "primary_state": "stale",
            "statuses": ["stale"],
            "message": STATE_COPY["stale"],
        }
        return _response(request, templates, view, 200)
    if error.code in {"ambiguous_category", "ambiguous_detail_category"}:
        choices = tuple(error.choices)
        view = {
            **base,
            "primary_state": "validation-error",
            "message": VALIDATION_COPY,
            "choices": category_choices(base["form"], choices),
            "choice_values": choices,
            "response_kind": "category-choice",
        }
        return _response(request, templates, view, 422 if _enhanced(request) else 200)
    view = {
        **base,
        "primary_state": "validation-error",
        "message": VALIDATION_COPY,
        "field_error": VALIDATION_COPY,
    }
    status = 422 if _enhanced(request) else 200
    return _response(request, templates, view, status)


def _parse_request(query: dict[str, str]) -> SearchRequest:
    target = query.get("target_price_won", "")
    tolerance = query.get("price_tolerance_pct", "")
    page = query.get("page", "1")
    return SearchRequest.model_validate(
        {
            "product_name": query.get("product_name", ""),
            "category_code": query.get("category_code") or None,
            "detail_category_code": query.get("detail_category_code") or None,
            "spec_text": query.get("spec_text", ""),
            "target_price_won": None if not target else int(target),
            "price_unit": query.get("price_unit") or None,
            "price_tolerance_pct": None if not tolerance else Decimal(tolerance),
            "page": int(page),
            "page_size": 50,
        }
    )


def _enhanced(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch"


def _response(
    request: Request,
    templates: Environment,
    view: dict[str, ViewValue],
    status: int,
) -> HTMLResponse | JSONResponse:
    if _enhanced(request):
        html = _render(templates, "results.html", view)
        payload = {
            "html": html,
            "primary_state": view["primary_state"],
            "kind": view.get("response_kind", "results"),
            "choices": view.get("choice_values", []),
        }
        return JSONResponse(payload, status)
    return _template(templates, "index.html", view, status)


def _template(
    templates: Environment,
    name: str,
    view: dict[str, ViewValue],
    status: int,
) -> HTMLResponse:
    return HTMLResponse(_render(templates, name, view), status)


def _render(
    templates: Environment,
    name: str,
    view: dict[str, ViewValue],
) -> str:
    template = templates.get_template(name)
    return template.render(**view)
