"""Validate and execute a release-pinned, read-only product search."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Final

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.normalize.numbers import (
    InvalidQuantityError,
    UnsupportedNumberError,
)
from g2b_compare.normalize.spec_types import (
    RangeParseError,
    RelationParseError,
    SpecSemantic,
    UnitDimensionError,
)
from g2b_compare.normalize.specs import parse_specs
from g2b_compare.normalize.text import normalize_text
from g2b_compare.normalize.units import UnitAliasError
from g2b_compare.ranking.topk import RankableProduct

from .comparators import (
    ComparatorView,
    ProductRecord,
    ScoredRecord,
    compare_product,
    prepare_comparator_context,
    score_pool,
    validate_cached,
)
from .search_models import (
    CategoryRef,
    SearchReader,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchServiceError,
    SpecSearchReader,
)

if TYPE_CHECKING:
    from g2b_compare.ranking.features import PreparedFeatureContext

    from .release_models import ReleasePin

PRICE_STEP: Final = Decimal("0.01")
DEFAULT_TOLERANCE: Final = Decimal("25.00")
STALE_SNAPSHOT: Final = "stale_snapshot"
PAGE_OVERFLOW: Final = "page_overflow"
AMBIGUOUS_DETAIL: Final = "ambiguous_detail_category"
AMBIGUOUS_CATEGORY: Final = "ambiguous_category"
UNKNOWN_CATEGORY: Final = "unknown_category"
UNKNOWN_DETAIL: Final = "unknown_detail_category"
DETAIL_PARENT_MISMATCH: Final = "detail_category_parent_mismatch"
PRICE_UNIT_REQUIRED: Final = "price_unit_required"
UNKNOWN_PRICE_UNIT: Final = "unknown_price_unit"
INVALID_SPEC_FILTER: Final = "invalid_spec_filter"
SPEC_PARSE_ERRORS: Final = (
    InvalidQuantityError,
    UnsupportedNumberError,
    RangeParseError,
    RelationParseError,
    UnitDimensionError,
    UnitAliasError,
)


def execute_search(request: SearchRequest, reader: SearchReader) -> SearchResponse:
    """Run category, price, scoring, pagination, and comparator resolution."""
    pin = reader.pin_active_release()
    if reader.is_stale(pin):
        raise SearchServiceError(code=STALE_SNAPSHOT)
    categories = reader.categories(pin)
    products = reader.exact_products(pin, request.product_name)
    selected, pool = _select_category(request, categories, products)
    semantics = _parse_spec_filter(request.spec_filter)
    source_by_product: dict[str, tuple[str, ...]] = {}
    if semantics:
        if not isinstance(reader, SpecSearchReader):
            raise SearchServiceError(code=INVALID_SPEC_FILTER)
        matches = reader.matching_specs(pin, semantics)
        source_by_product = {item.product_id: item.source_kinds for item in matches}
        pool = tuple(
            item for item in pool if item.rankable.product_id in source_by_product
        )
    if not pool:
        return _empty_response(request, pin, selected)
    facets = (
        reader.spec_facets(
            pin,
            tuple(item.rankable.product_id for item in pool),
        )
        if isinstance(reader, SpecSearchReader)
        else ()
    )
    price_unit, tolerance = _resolve_price(request, pool)
    query_anchor = _query_anchor(request, selected, price_unit)
    scored = score_pool(query_anchor, pool)
    ordered = sorted(
        scored,
        key=lambda item: _result_key(item, request, price_unit, tolerance),
    )
    if request.page > (len(ordered) + 49) // 50:
        raise SearchServiceError(code=PAGE_OVERFLOW)
    page_rows = ordered[(request.page - 1) * 50 : request.page * 50]
    cached_rows = (
        tuple(None for _item in page_rows)
        if semantics
        else tuple(
            reader.cached_comparators(pin, item.record.rankable.product_id)
            for item in page_rows
        )
    )
    context = (
        None
        if all(cached is not None for cached in cached_rows)
        else prepare_comparator_context(pool)
    )
    results = tuple(
        SearchResult(
            item.record,
            item,
            _within_tolerance(item.record, request, price_unit, tolerance),
            _comparators(item.record, pool, cached, context),
            source_by_product.get(item.record.rankable.product_id, ()),
        )
        for item, cached in zip(page_rows, cached_rows, strict=True)
    )
    return SearchResponse(
        "ok",
        pin,
        selected,
        price_unit,
        tolerance,
        len(ordered),
        request.page,
        50,
        results,
        facets,
    )


def _parse_spec_filter(raw: str) -> tuple[SpecSemantic, ...]:
    if not raw:
        return ()
    try:
        semantics = parse_specs(raw).semantics
    except SPEC_PARSE_ERRORS as error:
        raise SearchServiceError(code=INVALID_SPEC_FILTER) from error
    if not semantics:
        raise SearchServiceError(code=INVALID_SPEC_FILTER)
    return semantics


def _select_category(
    request: SearchRequest,
    categories: tuple[CategoryRef, ...],
    products: tuple[ProductRecord, ...],
) -> tuple[CategoryRef | None, tuple[ProductRecord, ...]]:
    requested = _requested_category(request, categories)
    groups = tuple(
        sorted(
            {item.rankable.category_key for item in products},
            key=lambda item: (item[0].encode(), item[1].encode()),
        )
    )
    if requested is not None:
        return requested, tuple(
            item for item in products if item.rankable.category_key == _key(requested)
        )
    if request.category_code is not None:
        groups = tuple(item for item in groups if item[0] == request.category_code)
        if len(groups) > 1:
            raise SearchServiceError(
                code=AMBIGUOUS_DETAIL,
                choices=tuple(item[1] for item in groups),
            )
    elif len(groups) > 1:
        raise SearchServiceError(
            code=AMBIGUOUS_CATEGORY,
            choices=tuple(f"{upper}/{detail}" for upper, detail in groups),
        )
    if not groups:
        return None, ()
    selected = CategoryRef(*groups[0])
    return selected, tuple(
        item for item in products if item.rankable.category_key == groups[0]
    )


def _requested_category(
    request: SearchRequest, categories: tuple[CategoryRef, ...]
) -> CategoryRef | None:
    if request.category_code is None:
        return None
    upper = tuple(
        item for item in categories if item.upper_code == request.category_code
    )
    if not upper:
        raise SearchServiceError(code=UNKNOWN_CATEGORY)
    if request.detail_category_code is None:
        return None
    detail = tuple(
        item for item in categories if item.detail_code == request.detail_category_code
    )
    if not detail:
        raise SearchServiceError(code=UNKNOWN_DETAIL)
    exact = tuple(
        item for item in upper if item.detail_code == request.detail_category_code
    )
    if not exact:
        raise SearchServiceError(code=DETAIL_PARENT_MISMATCH)
    return exact[0]


def _resolve_price(
    request: SearchRequest, pool: tuple[ProductRecord, ...]
) -> tuple[str | None, Decimal | None]:
    if request.target_price_won is None:
        return None, None
    units = tuple(
        sorted(
            {
                item.rankable.price.unit_key
                for item in pool
                if item.rankable.price.active
                and item.rankable.price.unit_key is not None
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    supplied = normalize_text(request.price_unit or "").derived or None
    if supplied is None and len(units) != 1:
        raise SearchServiceError(code=PRICE_UNIT_REQUIRED, choices=units)
    selected = units[0] if supplied is None else supplied
    if selected not in units:
        raise SearchServiceError(code=UNKNOWN_PRICE_UNIT, choices=units)
    tolerance = (
        DEFAULT_TOLERANCE
        if request.price_tolerance_pct is None
        else request.price_tolerance_pct
    )
    return selected, tolerance.quantize(PRICE_STEP, rounding=ROUND_HALF_EVEN)


def _query_anchor(
    request: SearchRequest, category: CategoryRef | None, unit: str | None
) -> RankableProduct:
    active = request.target_price_won is not None and unit is not None
    price = ComparisonPrice(
        active=active,
        amount_won=request.target_price_won,
        unit_key=unit,
        offer_key=None,
        reason=None if active else "query-price-absent",
    )
    return RankableProduct(
        product_id="__query__",
        category_key=("", "") if category is None else _key(category),
        product_name_key=normalize_text(request.product_name).derived,
        option_text=normalize_text(request.spec_text).derived,
        active=True,
        price=price,
    )


def _result_key(
    item: ScoredRecord,
    request: SearchRequest,
    selected_unit: str | None,
    tolerance: Decimal | None,
) -> tuple[bool, bool, Decimal, bytes]:
    within = _within_tolerance(item.record, request, selected_unit, tolerance)
    return (
        request.target_price_won is not None and not bool(within),
        item.scores.score is None,
        -(item.scores.score or Decimal(0)),
        item.record.rankable.product_id.encode("utf-8"),
    )


def _within_tolerance(
    record: ProductRecord,
    request: SearchRequest,
    selected_unit: str | None,
    tolerance: Decimal | None,
) -> bool | None:
    if request.target_price_won is None or tolerance is None:
        return None
    price = record.rankable.price
    if not price.active or price.amount_won is None or price.unit_key != selected_unit:
        return False
    target = Decimal(request.target_price_won)
    fraction = tolerance / Decimal(100)
    return target * (1 - fraction) <= price.amount_won <= target * (1 + fraction)


def _comparators(
    anchor: ProductRecord,
    pool: tuple[ProductRecord, ...],
    cached: tuple[ComparatorView, ...] | None,
    context: PreparedFeatureContext | None,
) -> tuple[ComparatorView, ComparatorView, ComparatorView]:
    if cached is not None:
        return validate_cached(anchor.rankable.product_id, cached)
    return compare_product(anchor, pool, context)


def _empty_response(
    request: SearchRequest, pin: ReleasePin, category: CategoryRef | None
) -> SearchResponse:
    if request.page > 1:
        raise SearchServiceError(code=PAGE_OVERFLOW)
    return SearchResponse(
        "no-matches", pin, category, None, None, 0, request.page, 50, ()
    )


def _key(category: CategoryRef) -> tuple[str, str]:
    return category.upper_code, category.detail_code
