"""Serve SSR GET searches and equivalent enhanced responses."""

from __future__ import annotations

import sqlite3
from decimal import InvalidOperation
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from g2b_compare.services.release_models import ReleaseContractError
from g2b_compare.services.release_reader import NO_READY_RELEASE
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchReader, SearchServiceError

from .navigation import add_pagination
from .rendering import (
    STATE_COPY,
    VALIDATION_COPY,
    is_enhanced_request,
    parse_search_request,
    render_response,
    search_error_response,
)
from .state import parse_statuses, result_state, sanitize_statuses
from .viewmodels import quota_status_view, search_view

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jinja2 import Environment

    from g2b_compare.services.release_models import ReleasePin

    from .types import ViewValue


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
    """Bind typed application dependencies to the local-snapshot HTTP route."""
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
        **quota_status_view(reader),
    }
    if not submitted:
        return _initial_response(request, reader, templates, base)
    try:
        search_request = parse_search_request(dict(query))
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
    try:
        result = execute_search(search_request, reader)
        view = {
            **base,
            **search_view(
                result,
                link_manifests,
                tuple(request.query_params.multi_items()),
            ),
        }
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
        return render_response(request, templates, view, 200)
    except SearchServiceError as error:
        return search_error_response(request, templates, base, error, results_path="/")
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
        return render_response(request, templates, base, 200)
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
    return render_response(request, templates, view, status)
