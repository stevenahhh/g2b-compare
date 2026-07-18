"""Project service contracts into escaped template values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .links import product_link

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from g2b_compare.services.comparator_models import ProductRecord
    from g2b_compare.services.search_models import SearchResponse, SearchResult

    from .types import ViewValue

PROVENANCE_OPTION = "배송내역에서 추가선택 역할 관측됨 — 본품 관계 미확정"
PROVENANCE_CURATED = "사용자 내역서에 관계 명시됨"
PROVENANCE_NONE = "연결 근거 없음 — 본품 관계를 추정하지 않음"
PRICE_REASONS = {
    "incompatible_price",
    "missing-unit",
    "mixed-unit",
    "missing-price",
    "no-active-offer",
}


def search_view(
    response: SearchResponse,
    link_manifests: Mapping[str, Mapping[str, ViewValue]],
) -> dict[str, ViewValue]:
    """Build the deterministic result-page view."""
    projected = [
        _row_view(item, link_manifests.get(item.product.rankable.product_id, {}))
        for item in response.results
    ]
    rows = [row for row, _statuses in projected]
    statuses = sorted(
        {status for _row, row_statuses in projected for status in row_statuses},
        key=str.encode,
    )
    return {
        "primary_state": "no-matches" if not rows else "current-results",
        "statuses": statuses,
        "rows": rows,
        "total": response.total_results,
        "page": response.page,
        "page_size": 50,
        "data_as_of": response.release.data_as_of,
    }


def _row_view(
    result: SearchResult,
    link_manifest: Mapping[str, ViewValue],
) -> tuple[dict[str, ViewValue], tuple[str, ...]]:
    record = result.product
    statuses: list[str] = []
    if record.attribute_coverage not in {"1", "1/1", "100%"}:
        statuses.append("partial-attribute")
    if any(slot.candidate is None for slot in result.comparators):
        statuses.append("insufficient-comparator")
    if not record.rankable.price.active:
        statuses.append("incompatible-price")
    comparators: list[dict[str, ViewValue]] = []
    for slot in result.comparators:
        missing = set(slot.missing_reasons)
        if "no_comparison_evidence" in missing:
            statuses.append("no-evidence")
        if any(reason in PRICE_REASONS or "price" in reason for reason in missing):
            statuses.append("incompatible-price")
        comparators.append(
            {
                "rank": slot.rank,
                "status": slot.status,
                "name": (
                    None if slot.candidate is None else slot.candidate.product_name_raw
                ),
                "score": None if slot.scores is None else _number(slot.scores.score),
                "reasons": slot.missing_reasons,
            }
        )
    rankable = record.rankable
    price = rankable.price
    link = product_link(link_manifest, rankable.product_id)
    row_statuses = tuple(sorted(set(statuses), key=str.encode))
    return {
        "id": rankable.product_id,
        "name": record.product_name_raw,
        "spec": rankable.option_text or "—",
        "price": _number(price.amount_won),
        "unit": price.unit_key or "—",
        "score": _number(result.scores.scores.score),
        "data_as_of": record.data_as_of,
        "provenance": _provenance(record),
        "comparators": comparators,
        "statuses": row_statuses,
        "link_href": link.href,
        "copy_id": link.copy_id,
    }, row_statuses


def _number(value: Decimal | int | None) -> str | None:
    return None if value is None else format(value, "f")


def _provenance(record: ProductRecord) -> str:
    if record.observed_option_roles:
        return PROVENANCE_OPTION
    if record.curated_relations:
        return PROVENANCE_CURATED
    return PROVENANCE_NONE
