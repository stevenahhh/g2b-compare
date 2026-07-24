"""Server-rendered estimate draft CRUD routes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, final
from urllib.parse import parse_qs

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field

from g2b_compare.services import (
    EstimateDraft,
    EstimateExporter,
    EstimateExportError,
    EstimateFullError,
    EstimateHistoryStore,
    EstimateNotFoundError,
    EstimateStore,
)

from .estimate_selection import (
    COMPARISON_SLOT_COUNT,
    comparison_views,
    resolve_selection,
    seed_comparisons,
)

if TYPE_CHECKING:
    from pathlib import Path

    from jinja2 import Environment

TEMPLATE_SHA256: Final = (
    "f344d2fcd12612170677eacc8b6ee4798ef730b8f5ea91b40ba8d7fcf0d694e4"
)
KST: Final = timezone(timedelta(hours=9))
EXCEL_MEDIA_TYPE: Final = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
QUANTITY_INVALID: Final = "수량을 확인해야 함"
QUANTITY_POSITIVE: Final = "수량은 0보다 커야 함"


class QuantityPatch(BaseModel):
    """One debounced quantity change from the editor."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    quantity: Annotated[Decimal, Field(gt=0)]


@final
class EstimateEndpoints:
    """HTTP projection over one shared estimate store."""

    def __init__(self, database: Path, templates: Environment) -> None:
        """Bind request handlers to one database and template environment."""
        self.database = database
        self.templates = templates
        self.store = EstimateStore(database)
        self.history = EstimateHistoryStore(database)

    def drafts(self, request: Request) -> HTMLResponse:
        """Render saved non-empty drafts without creating a new one."""
        self.history.discard_empty_drafts()
        html = self.templates.get_template("estimates.html").render(
            request=request,
            drafts=self.history.list_saved_drafts(),
        )
        return HTMLResponse(html)

    def create(self) -> RedirectResponse:
        """Create one automatically named draft and open its editor."""
        draft = self._new_draft()
        return RedirectResponse(f"/estimates/{draft.id}", status_code=303)

    def _new_draft(self) -> EstimateDraft:
        """Create one automatically named empty draft."""
        self.history.discard_empty_drafts()
        now = datetime.now(KST)
        sequence = self.store.draft_count() + 1
        title = f"{sequence}-{now:%Y%m%d-%H%M%S}"
        return self.store.create_draft(title, TEMPLATE_SHA256)

    async def editor(self, request: Request, estimate_id: str) -> HTMLResponse:
        """Render one persisted draft with its comparison snapshots."""
        try:
            draft = self.store.get_draft(estimate_id)
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        comparisons = comparison_views(self.database, draft)
        export_ready = bool(draft.lines) and all(
            len(comparisons.get(line.id, ())) == COMPARISON_SLOT_COUNT
            for line in draft.lines
        )
        html = self.templates.get_template("estimate.html").render(
            request=request,
            draft=draft,
            comparisons=comparisons,
            export_ready=export_ready,
        )
        return HTMLResponse(html)

    async def add_line(
        self,
        request: Request,
        estimate_id: str,
    ) -> RedirectResponse:
        """Append one trusted catalog selection to a draft."""
        form = await _urlencoded_form(request)
        product_id = form.get("product_id", "").strip()
        parent_product_id = form.get("parent_product_id", "").strip() or None
        relation_id = form.get("relation_id", "").strip() or None
        try:
            quantity = Decimal(form.get("quantity", "1"))
        except InvalidOperation as error:
            raise HTTPException(status_code=422, detail=QUANTITY_INVALID) from error
        if not quantity.is_finite() or quantity <= 0:
            raise HTTPException(status_code=422, detail=QUANTITY_POSITIVE)
        selection = resolve_selection(
            self.database,
            product_id,
            parent_product_id,
            relation_id,
            quantity,
        )
        try:
            line = self.store.add_line(estimate_id, selection)
            seed_comparisons(self.database, line)
        except EstimateFullError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return RedirectResponse(f"/estimates/{estimate_id}", status_code=303)

    async def add_line_to_new_draft(self, request: Request) -> RedirectResponse:
        """Create a draft and append one catalog selection to it."""
        return await self.add_line(request, self._new_draft().id)

    def update_line(
        self,
        estimate_id: str,
        line_id: str,
        payload: Annotated[QuantityPatch, Body()],
    ) -> JSONResponse:
        """Persist one debounced quantity change."""
        try:
            line = self.store.update_quantity(estimate_id, line_id, payload.quantity)
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return JSONResponse({"quantity": format(line.quantity, "f")})

    def delete_line(self, estimate_id: str, line_id: str) -> Response:
        """Delete one estimate line."""
        try:
            self.store.delete_line(estimate_id, line_id)
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(status_code=204)

    def delete_draft(self, estimate_id: str) -> RedirectResponse:
        """Delete one saved estimate and return to the saved list."""
        try:
            self.history.delete_draft(estimate_id)
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return RedirectResponse("/estimates", status_code=303)

    def export(self, estimate_id: str) -> FileResponse:
        """Generate and download one fixed-template workbook."""
        try:
            draft = self.store.get_draft(estimate_id)
            timestamp = datetime.now(KST).strftime("%Y%m%d_%H%M")
            filename = f"{_safe_filename(draft.title)}_{timestamp}_관급내역서.xlsx"
            destination = self.database.parent / "exports" / filename
            _ = EstimateExporter(self.database).export(estimate_id, destination)
        except EstimateExportError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(destination, media_type=EXCEL_MEDIA_TYPE, filename=filename)


def build_estimate_router(database: Path, templates: Environment) -> APIRouter:
    """Bind estimate CRUD to the shared application database."""
    endpoint = EstimateEndpoints(database, templates)
    router = APIRouter()
    router.add_api_route("/estimates", endpoint.drafts, methods=["GET"])
    router.add_api_route("/estimates", endpoint.create, methods=["POST"])
    router.add_api_route(
        "/estimates/lines", endpoint.add_line_to_new_draft, methods=["POST"]
    )
    router.add_api_route("/estimates/{estimate_id}", endpoint.editor, methods=["GET"])
    router.add_api_route(
        "/estimates/{estimate_id}/delete", endpoint.delete_draft, methods=["POST"]
    )
    router.add_api_route(
        "/estimates/{estimate_id}/lines", endpoint.add_line, methods=["POST"]
    )
    line_path = "/estimates/{estimate_id}/lines/{line_id}"
    router.add_api_route(line_path, endpoint.update_line, methods=["PATCH"])
    router.add_api_route(line_path, endpoint.delete_line, methods=["DELETE"])
    router.add_api_route(
        "/estimates/{estimate_id}/export.xlsx", endpoint.export, methods=["GET"]
    )
    return router


async def _urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body).items() if values}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    return cleaned or "관급내역"
