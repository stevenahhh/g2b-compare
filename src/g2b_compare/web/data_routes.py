"""Shared-database status page for priority collection work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from g2b_compare.priority_store import PriorityStore

if TYPE_CHECKING:
    from pathlib import Path

    from jinja2 import Environment


def build_data_router(database: Path, templates: Environment) -> APIRouter:
    """Expose collection counts without starting external API work."""
    store = PriorityStore(database)
    router = APIRouter()

    def data_page(request: Request) -> HTMLResponse:
        return HTMLResponse(
            templates.get_template("data.html").render(
                request=request,
                status=store.status(),
            )
        )

    router.add_api_route("/data", data_page, methods=["GET"])
    return router
