"""Priority database list route."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from g2b_compare.priority_store import PriorityStore

if TYPE_CHECKING:
    from pathlib import Path

    from jinja2 import Environment


def build_priority_router(database: Path, templates: Environment) -> APIRouter:
    """Build the 30-row procurement-estimate style list route."""
    store = PriorityStore(database)
    router = APIRouter()

    def priority_list(
        request: Request,
        q: Annotated[str, Query(max_length=100)] = "",
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        result = store.list_lines("", page=page, page_size=30)
        html = templates.get_template("priority.html").render(
            request=request,
            query=q,
            result=result,
            status=store.status(),
        )
        return HTMLResponse(html)

    router.add_api_route(
        "/priority", priority_list, methods=["GET"], response_class=HTMLResponse
    )
    return router
