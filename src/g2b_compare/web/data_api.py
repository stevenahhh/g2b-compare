"""Core data-status JSON endpoint for the SPA data view."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from g2b_compare.priority_store import PriorityStore

from .api_models import DataStatusResponse

if TYPE_CHECKING:
    from pathlib import Path


def build_data_api_router(database: Path) -> APIRouter:
    """Build the core data-status route over the existing priority store."""
    router = APIRouter()

    def data_status() -> DataStatusResponse | JSONResponse:
        try:
            status = PriorityStore(database).status()
        except (sqlite3.DatabaseError, OSError):
            return JSONResponse(
                status_code=503,
                content={"error": "data-unavailable"},
            )
        ready = status.product_count > 0
        return DataStatusResponse(
            company_count=status.company_count,
            option_row_count=status.option_row_count,
            unique_option_count=status.unique_option_count,
            product_count=status.product_count,
            relation_count=status.relation_count,
            pending_api_target_count=status.pending_api_target_count,
            pending_site_product_count=status.pending_site_product_count,
            ready=ready,
            readiness="ready" if ready else "empty",
        )

    router.add_api_route(
        "/api/data/status",
        data_status,
        methods=["GET"],
        response_model=DataStatusResponse,
    )
    return router
