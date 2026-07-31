"""Idempotent full-document JSON API for saved estimates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Final, Literal

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import Response, StreamingResponse
from pydantic import TypeAdapter

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_text, query
from g2b_compare.priority_attributes import parse_product_attributes
from g2b_compare.services import (
    EstimateDraft,
    EstimateFullError,
    EstimateHistoryStore,
    EstimateLineInput,
    EstimateNotFoundError,
    EstimateStore,
)
from g2b_compare.services.estimate_store import MAX_ESTIMATE_LINES

from .api_models import (
    CatalogAttributeResponse,
    EstimateComparisonResponse,
    EstimateDocumentRequest,
    EstimateDocumentResponse,
    EstimateLineResponse,
    EstimateSummaryResponse,
)
from .estimate_events import ESTIMATE_EVENTS, EstimateEvent, estimate_event_stream
from .estimate_routes import TEMPLATE_SHA256
from .estimate_selection import (
    COMPARISON_SLOT_COUNT,
    ComparisonView,
    comparison_views,
    seed_document_comparisons_in_transaction,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path as FilePath

CLIENT_ID_PATTERN: Final = r"^[0-9a-fA-F]{32}$"
ComparisonSlot = Literal["A", "B", "C"]
COMPARISON_SLOT_ADAPTER: Final[TypeAdapter[ComparisonSlot]] = TypeAdapter(
    ComparisonSlot
)


def build_estimate_api_router(database: FilePath) -> APIRouter:
    """Build JSON estimate routes over the existing SQLite snapshot tables."""
    store = EstimateStore(database)
    history = EstimateHistoryStore(database)
    router = APIRouter()

    @router.get("/api/estimates", response_model=list[EstimateSummaryResponse])
    def list_estimates() -> list[EstimateSummaryResponse]:
        return [
            EstimateSummaryResponse(
                id=draft.id,
                title=draft.title,
                updated_at=draft.updated_at,
                line_count=draft.line_count,
            )
            for draft in history.list_saved_drafts()
        ]

    @router.get("/api/estimates/events", include_in_schema=False)
    def estimate_events() -> StreamingResponse:
        return StreamingResponse(
            estimate_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/estimates/{estimate_id}", response_model=EstimateDocumentResponse)
    def get_estimate(
        estimate_id: Annotated[str, Path(pattern=CLIENT_ID_PATTERN)],
    ) -> EstimateDocumentResponse:
        try:
            draft = store.get_draft(estimate_id)
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return _document_response(database, draft)

    @router.put("/api/estimates/{estimate_id}", response_model=EstimateDocumentResponse)
    def put_estimate(
        estimate_id: Annotated[str, Path(pattern=CLIENT_ID_PATTERN)],
        payload: EstimateDocumentRequest,
    ) -> EstimateDocumentResponse:
        if len(payload.lines) > MAX_ESTIMATE_LINES:
            raise HTTPException(
                status_code=409,
                detail=f"estimate {estimate_id} already has 9 lines",
            )
        lines = tuple(
            (
                line.id,
                EstimateLineInput(
                    line_kind=line.line_kind,
                    product_id=line.product_id,
                    parent_product_id=line.parent_product_id,
                    relation_id=line.relation_id,
                    offer_operation=line.offer_operation,
                    offer_key=line.offer_key,
                    item_name_snapshot=line.item_name_snapshot,
                    spec_snapshot=line.spec_snapshot,
                    company_snapshot=line.company_snapshot,
                    unit_snapshot=line.unit_snapshot,
                    unit_price_won_snapshot=line.unit_price_won_snapshot,
                    quantity=line.quantity,
                ),
            )
            for line in payload.lines
        )
        try:
            draft = store.replace_draft(
                estimate_id,
                payload.title,
                TEMPLATE_SHA256,
                lines,
                seed_document_comparisons_in_transaction,
            )
        except EstimateFullError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        ESTIMATE_EVENTS.publish(EstimateEvent("estimate-saved", estimate_id))
        return _document_response(database, draft)

    router.add_api_route(
        "/api/estimates/{estimate_id}/refresh-comparisons",
        _build_refresh_comparisons_endpoint(database, store),
        methods=["POST"],
        response_model=EstimateDocumentResponse,
        name="refresh_estimate_comparisons",
    )

    @router.delete("/api/estimates/{estimate_id}", status_code=204)
    def delete_estimate(
        estimate_id: Annotated[str, Path(pattern=CLIENT_ID_PATTERN)],
    ) -> Response:
        store.delete_draft_if_exists(estimate_id)
        ESTIMATE_EVENTS.publish(EstimateEvent("estimate-deleted", estimate_id))
        return Response(status_code=204)

    return router


def _build_refresh_comparisons_endpoint(
    database: FilePath,
    store: EstimateStore,
) -> Callable[[str], EstimateDocumentResponse]:
    def refresh_estimate_comparisons(
        estimate_id: Annotated[str, Path(pattern=CLIENT_ID_PATTERN)],
    ) -> EstimateDocumentResponse:
        try:
            draft = store.refresh_comparisons(
                estimate_id,
                seed_document_comparisons_in_transaction,
            )
        except EstimateNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        ESTIMATE_EVENTS.publish(EstimateEvent("estimate-saved", estimate_id))
        return _document_response(database, draft)

    return refresh_estimate_comparisons


def _document_response(
    database: FilePath,
    draft: EstimateDraft,
) -> EstimateDocumentResponse:
    comparisons = comparison_views(database, draft)
    lines = [
        EstimateLineResponse(
            id=line.id,
            line_no=line.line_no,
            line_kind=line.line_kind,
            product_id=line.product_id,
            parent_product_id=line.parent_product_id,
            relation_id=line.relation_id,
            offer_operation=line.offer_operation,
            offer_key=line.offer_key,
            item_name_snapshot=line.item_name_snapshot,
            spec_snapshot=line.spec_snapshot,
            company_snapshot=line.company_snapshot,
            unit_snapshot=line.unit_snapshot,
            unit_price_won_snapshot=line.unit_price_won_snapshot,
            quantity=line.quantity,
            attributes=_attributes(database, line.product_id, line.parent_product_id),
            comparisons=[_comparison_response(item) for item in comparisons[line.id]],
        )
        for line in draft.lines
    ]
    return EstimateDocumentResponse(
        id=draft.id,
        title=draft.title,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        lines=lines,
        export_ready=all(
            len(comparisons[line.id]) == COMPARISON_SLOT_COUNT for line in draft.lines
        ),
    )


def _comparison_response(item: ComparisonView) -> EstimateComparisonResponse:
    return EstimateComparisonResponse(
        slot=COMPARISON_SLOT_ADAPTER.validate_python(item.slot),
        product_id=item.product_id,
        relation_id=item.relation_id,
        company_snapshot=item.company,
        spec_snapshot=item.spec,
        price_won_snapshot=item.price_won,
        g2b_url=item.detail_url,
        attributes=[
            CatalogAttributeResponse.model_validate(attribute.model_dump())
            for attribute in item.attributes
        ],
    )


def _attributes(
    database: FilePath,
    product_id: str,
    parent_product_id: str | None,
) -> list[CatalogAttributeResponse]:
    with connect(database) as connection:
        row = query(
            connection,
            """
            SELECT raw_json FROM priority_products
            WHERE product_id IN (?, ?)
            ORDER BY CASE WHEN product_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (product_id, parent_product_id, product_id),
        ).fetchone()
    if row is None:
        return []
    return [
        CatalogAttributeResponse.model_validate(attribute.model_dump())
        for attribute in parse_product_attributes(as_text(row[0]))
    ]
