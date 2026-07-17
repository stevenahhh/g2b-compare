"""Canonical typed JSON boundary for search responses."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, ClassVar, Literal, assert_never

from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.db.hashes import JsonValue, canonical_json

if TYPE_CHECKING:
    from decimal import Decimal

    from g2b_compare.ranking.explain import ScoreBreakdown

    from .comparator_models import (
        ComparatorScores,
        ComparatorView,
        MatchedQuantity,
        ProductRecord,
    )
    from .search_models import SearchResponse, SearchResult

JSON_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _Document(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class _ScoreDocument(_Document):
    L: str | None
    F: str | None
    U: str | None
    P: str | None
    S: str | None
    coverage: str | None


class _MatchedQuantityDocument(_Document):
    anchor_start: int
    candidate_start: int
    attribute_key: str
    dimension: str
    value_similarity: str


class _OptionRoleDocument(_Document):
    source_snapshot_id: int
    source_row_key: str
    delivery_request_key: str
    item_sequence: str
    change_sequence: str
    role_raw: str
    observed_at: str


class _CuratedRelationDocument(_Document):
    relation_id: str
    parent_id: str
    child_id: str
    source_type: str
    source_sha: str
    sheet_name: str
    row_no: int


class _PriceDocument(_Document):
    active: bool
    amount_won: int | None
    unit_key: str | None
    offer_key: tuple[str, str] | None
    reason: str | None


class _ProductDocument(_Document):
    product_id: str
    category: tuple[str, str]
    product_name: str
    option_text: str
    price: _PriceDocument
    data_as_of: str
    attribute_coverage: str
    observed_option_roles: tuple[_OptionRoleDocument, ...]
    curated_relations: tuple[_CuratedRelationDocument, ...]


class _ComparatorDocument(_Document):
    rank: int
    status: Literal[
        "ok",
        "no_comparison_evidence",
        "insufficient_candidates",
    ]
    candidate: _ProductDocument | None
    scores: _ScoreDocument | None
    matched_quantities: tuple[_MatchedQuantityDocument, ...]
    missing_reasons: tuple[str, ...]


class _ResultDocument(_Document):
    product: _ProductDocument
    scores: _ScoreDocument
    matched_quantities: tuple[_MatchedQuantityDocument, ...]
    missing_reasons: tuple[str, ...]
    within_price_tolerance: bool | None
    comparators: tuple[_ComparatorDocument, _ComparatorDocument, _ComparatorDocument]


class _ReleaseDocument(_Document):
    bundle_id: int
    ready_attempt_no: int
    materialization_id: int
    index_version_id: int
    relation_snapshot_id: int
    ranking_version: str
    normalization_version: str
    materialization_policy_version: str
    materialization_source_sha: str
    index_artifact_sha: str
    index_manifest_sha: str
    relation_source_manifest_sha: str
    relation_content_sha: str
    data_as_of: str


class _CategoryDocument(_Document):
    upper_code: str
    detail_code: str


class _SearchResponseDocument(_Document):
    schema_version: Literal["1"]
    status: Literal["ok", "no-matches"]
    release: _ReleaseDocument
    selected_category: _CategoryDocument | None
    selected_price_unit: str | None
    price_tolerance_pct: str | None
    total_results: int
    page: int
    page_size: Literal[50]
    results: tuple[_ResultDocument, ...]


def encode_search_response(response: SearchResponse) -> bytes:
    """Return canonical UTF-8 bytes without a trailing newline."""
    document = _SearchResponseDocument(
        schema_version="1",
        status=response.status,
        release=_ReleaseDocument.model_validate(response.release, from_attributes=True),
        selected_category=(
            None
            if response.selected_category is None
            else _CategoryDocument.model_validate(
                response.selected_category,
                from_attributes=True,
            )
        ),
        selected_price_unit=response.selected_price_unit,
        price_tolerance_pct=_fixed(response.price_tolerance_pct),
        total_results=response.total_results,
        page=response.page,
        page_size=response.page_size,
        results=tuple(_result(item) for item in response.results),
    )
    value = JSON_ADAPTER.validate_python(document.model_dump(mode="json"))
    return canonical_json(_normalize(value)).encode("utf-8")


def search_response_schema_bytes() -> bytes:
    """Return the canonical JSON Schema for the response document."""
    value = JSON_ADAPTER.validate_python(_SearchResponseDocument.model_json_schema())
    return canonical_json(_normalize(value)).encode("utf-8")


def _result(result: SearchResult) -> _ResultDocument:
    return _ResultDocument(
        product=_product(result.product),
        scores=_query_scores(result.scores.scores),
        matched_quantities=_matched(result.scores.matched_quantities),
        missing_reasons=result.scores.missing_reasons,
        within_price_tolerance=result.within_price_tolerance,
        comparators=(
            _comparator(result.comparators[0]),
            _comparator(result.comparators[1]),
            _comparator(result.comparators[2]),
        ),
    )


def _comparator(view: ComparatorView) -> _ComparatorDocument:
    return _ComparatorDocument(
        rank=view.rank,
        status=view.status,
        candidate=None if view.candidate is None else _product(view.candidate),
        scores=_comparator_scores(view.scores),
        matched_quantities=_matched(view.matched_quantities),
        missing_reasons=view.missing_reasons,
    )


def _product(record: ProductRecord) -> _ProductDocument:
    price = record.rankable.price
    return _ProductDocument(
        product_id=record.rankable.product_id,
        category=record.rankable.category_key,
        product_name=record.product_name_raw,
        option_text=record.rankable.option_text,
        price=_PriceDocument(
            active=price.active,
            amount_won=price.amount_won,
            unit_key=price.unit_key,
            offer_key=price.offer_key,
            reason=price.reason,
        ),
        data_as_of=record.data_as_of,
        attribute_coverage=record.attribute_coverage,
        observed_option_roles=tuple(
            _OptionRoleDocument.model_validate(item, from_attributes=True)
            for item in record.observed_option_roles
        ),
        curated_relations=tuple(
            _CuratedRelationDocument.model_validate(item, from_attributes=True)
            for item in record.curated_relations
        ),
    )


def _matched(
    values: tuple[MatchedQuantity, ...],
) -> tuple[_MatchedQuantityDocument, ...]:
    return tuple(
        _MatchedQuantityDocument(
            anchor_start=item.anchor_start,
            candidate_start=item.candidate_start,
            attribute_key=item.attribute_key,
            dimension=item.dimension,
            value_similarity=_fixed(item.value_similarity) or "0.000000",
        )
        for item in values
    )


def _query_scores(scores: ScoreBreakdown) -> _ScoreDocument:
    return _ScoreDocument(
        L=_fixed(scores.lexical),
        F=_fixed(scores.fuzzy),
        U=_fixed(scores.structured),
        P=_fixed(scores.price),
        S=_fixed(scores.score),
        coverage=_fixed(scores.coverage),
    )


def _comparator_scores(scores: ComparatorScores | None) -> _ScoreDocument | None:
    if scores is None:
        return None
    return _ScoreDocument(
        L=_fixed(scores.lexical),
        F=_fixed(scores.fuzzy),
        U=_fixed(scores.structured),
        P=_fixed(scores.price),
        S=_fixed(scores.score),
        coverage=_fixed(scores.coverage),
    )


def _fixed(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _normalize(value: JsonValue) -> JsonValue:
    match value:
        case str() as text:
            return unicodedata.normalize("NFKC", text.replace("\r\n", "\n"))
        case bool() | int() | None:
            return value
        case list() as values:
            return [_normalize(item) for item in values]
        case dict() as mapping:
            return {key: _normalize(mapping[key]) for key in mapping}
        case _:
            assert_never(value)
