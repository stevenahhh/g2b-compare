"""Project service contracts into escaped template values."""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlencode, urljoin, urlparse

from .links import SHOP_HOME, product_link

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from g2b_compare.services.comparator_models import ProductRecord
    from g2b_compare.services.search_models import (
        SearchReader,
        SearchResponse,
        SearchResult,
    )

    from .sqlite_reader import QuotaStatus
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
KST = timezone(timedelta(hours=9))


@runtime_checkable
class QuotaStatusReader(Protocol):
    """Expose a provider quota block before an active release exists."""

    def quota_status(self) -> QuotaStatus | None:
        """Return the persisted quota receipt when synchronization is deferred."""
        ...


def quota_status_view(reader: SearchReader) -> dict[str, ViewValue]:
    """Project a deferred provider quota receipt into template values."""
    if not isinstance(reader, QuotaStatusReader):
        return {}
    quota = reader.quota_status()
    if quota is None:
        return {}
    return {
        "quota_operation": quota.operation,
        "quota_resume_not_before": quota.resume_not_before.isoformat(),
        "quota_resume_display": quota.resume_not_before.astimezone(KST).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
    }


def search_view(
    response: SearchResponse,
    link_manifests: Mapping[str, Mapping[str, ViewValue]],
    query_items: tuple[tuple[str, str], ...] = (),
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
        "facets": [
            {
                "dimension": facet.dimension,
                "value": facet.display_value,
                "count": facet.count,
                "href": _facet_href(query_items, facet.filter_value),
            }
            for facet in response.facets[:12]
        ],
    }


def _row_view(
    result: SearchResult,
    link_manifest: Mapping[str, ViewValue],
) -> tuple[dict[str, ViewValue], tuple[str, ...]]:
    record = result.product
    statuses: list[str] = []
    if record.attribute_coverage not in {"1", "1/1", "100%", "live"}:
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
        if "same_corp_as_higher_slot" in missing:
            statuses.append("same-corp-slot")
        comparators.append(
            {
                "rank": slot.rank,
                "status": slot.status,
                "name": (
                    None
                    if slot.candidate is None
                    else slot.candidate.spec_name_raw or slot.candidate.product_name_raw
                ),
                "score": None if slot.scores is None else _number(slot.scores.score),
                "price": (
                    None
                    if slot.candidate is None
                    else _won(slot.candidate.rankable.price.amount_won)
                ),
                "unit": (
                    None
                    if slot.candidate is None
                    else slot.candidate.rankable.price.unit_key
                ),
                "reasons": slot.missing_reasons,
            }
        )
    rankable = record.rankable
    if result.spec_sources:
        statuses.append("spec-filter-active")
        statuses.extend(f"spec-source-{source}" for source in result.spec_sources)
    price = rankable.price
    link = product_link(
        link_manifest,
        rankable.product_id,
        contract_item_key=record.contract_item_key,
    )
    row_statuses = tuple(sorted(set(statuses), key=str.encode))
    return {
        "id": rankable.product_id,
        "name": record.product_name_raw,
        "title": record.spec_name_raw or record.product_name_raw,
        "spec": record.spec_name_raw or rankable.option_text or "—",
        "image_url": _safe_image_url(record.image_url),
        "supplier": record.supplier_name or "—",
        "contract_method": record.contract_method or "—",
        "delivery_condition": record.delivery_condition or "—",
        "purchase_type": record.purchase_type,
        "category_code": rankable.category_key[1],
        "price": _won(price.amount_won),
        "unit": price.unit_key or "—",
        "score": _number(result.scores.scores.score),
        "data_as_of": _display_date(record.data_as_of),
        "provenance": _provenance(record),
        "comparators": comparators,
        "statuses": row_statuses,
        "link_href": link.href,
        "copy_id": link.copy_id,
    }, row_statuses


def _number(value: Decimal | int | None) -> str | None:
    return None if value is None else format(value, "f")


def _won(value: int | None) -> str | None:
    return None if value is None else f"{value:,}"


def _display_date(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) < 8:
        return raw
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"


def _safe_image_url(raw: str) -> str | None:
    if not raw:
        return None
    resolved = urljoin(SHOP_HOME, raw)
    parsed = urlparse(resolved)
    if parsed.scheme != "https" or parsed.hostname is None:
        return None
    if parsed.hostname != "shop.g2b.go.kr" and not parsed.hostname.endswith(
        ".g2b.go.kr"
    ):
        return None
    return resolved


def _provenance(record: ProductRecord) -> str:
    if record.observed_option_roles:
        return PROVENANCE_OPTION
    if record.curated_relations:
        return PROVENANCE_CURATED
    return PROVENANCE_NONE


def _facet_href(
    query_items: tuple[tuple[str, str], ...],
    filter_value: str,
) -> str:
    kept = tuple(
        (key, value) for key, value in query_items if key not in {"spec_filter", "page"}
    )
    return f"/?{urlencode((*kept, ('spec_filter', filter_value)))}"
