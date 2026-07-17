"""Encode and verify typed persisted comparator payloads."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from g2b_compare.ranking.cache import CachePayload

from . import comparator_encoding as encoding
from .comparators import (
    ComparatorCacheError,
    ComparatorScores,
    ComparatorStatus,
    ComparatorView,
    MatchedQuantity,
    ObservedOptionRole,
    ProductRecord,
    validate_cached,
)

if TYPE_CHECKING:
    from g2b_compare.ranking.cache import CachedSlot, CacheJsonValue

type FixedDecimal = Annotated[
    str,
    StringConstraints(pattern=r"^-?\d+\.\d{6}$"),
]
EXPECTED_SLOTS: Final = (1, 2, 3)


class _BoundaryModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class _Scores(_BoundaryModel):
    lexical: FixedDecimal | None = Field(alias="L")
    fuzzy: FixedDecimal | None = Field(alias="F")
    structured: FixedDecimal | None = Field(alias="U")
    price: FixedDecimal | None = Field(alias="P")
    score: FixedDecimal | None = Field(alias="S")
    coverage: FixedDecimal | None


class _MatchedQuantity(_BoundaryModel):
    anchor_start: int
    candidate_start: int
    attribute_key: str
    dimension: str
    value_similarity: FixedDecimal


class _OptionRoleObservation(_BoundaryModel):
    source_snapshot_id: int
    source_row_key: str
    delivery_request_key: str
    item_sequence: int
    change_sequence: int
    role_raw: str
    observed_at: str


class _ComparatorDocument(_BoundaryModel):
    schema_version: Literal["1"]
    anchor_id: str
    slot: Literal[1, 2, 3]
    candidate_id: str | None
    scores: _Scores
    matched_quantities: list[_MatchedQuantity]
    missing_reasons: list[str]
    option_role_observations: list[_OptionRoleObservation]


def encode_comparator_payload(view: ComparatorView) -> CachePayload:
    """Encode one view using the exact cache schema and canonical array orders."""
    candidate = view.candidate
    scores = view.scores
    missing_reasons = sorted(
        {encoding.normalize_payload_text(item) for item in view.missing_reasons},
        key=lambda item: item.encode("utf-8"),
    )
    document: dict[str, CacheJsonValue] = {
        "anchor_id": encoding.normalize_payload_text(view.anchor_id),
        "candidate_id": (
            None
            if candidate is None
            else encoding.normalize_payload_text(candidate.rankable.product_id)
        ),
        "matched_quantities": [
            {
                "anchor_start": item.anchor_start,
                "attribute_key": encoding.normalize_payload_text(item.attribute_key),
                "candidate_start": item.candidate_start,
                "dimension": encoding.normalize_payload_text(item.dimension),
                "value_similarity": encoding.fixed_decimal(item.value_similarity),
            }
            for item in sorted(
                view.matched_quantities,
                key=lambda item: (
                    item.anchor_start,
                    item.candidate_start,
                    encoding.normalize_payload_text(item.attribute_key),
                    encoding.normalize_payload_text(item.dimension),
                ),
            )
        ],
        "missing_reasons": list(missing_reasons),
        "option_role_observations": (
            [] if candidate is None else _option_roles(candidate.observed_option_roles)
        ),
        "schema_version": "1",
        "scores": {
            "F": None if scores is None else encoding.fixed_decimal(scores.fuzzy),
            "L": None if scores is None else encoding.fixed_decimal(scores.lexical),
            "P": None if scores is None else encoding.fixed_decimal(scores.price),
            "S": None if scores is None else encoding.fixed_decimal(scores.score),
            "U": None if scores is None else encoding.fixed_decimal(scores.structured),
            "coverage": (
                None if scores is None else encoding.fixed_decimal(scores.coverage)
            ),
        },
        "slot": view.rank,
    }
    return CachePayload(document)


def validate_comparator_payloads(
    anchor_id: str,
    slots: tuple[CachedSlot, ...],
    products: tuple[ProductRecord, ...],
) -> tuple[ComparatorView, ComparatorView, ComparatorView]:
    """Decode canonical persisted slots without rerunning Ranking v1."""
    if (
        len(slots) != len(EXPECTED_SLOTS)
        or tuple(item.slot for item in slots) != EXPECTED_SLOTS
    ):
        raise ComparatorCacheError
    by_id = {item.rankable.product_id: item for item in products}
    views: list[ComparatorView] = []
    for observed in slots:
        try:
            document = _ComparatorDocument.model_validate(observed.payload.root)
        except ValidationError as error:
            raise ComparatorCacheError from error
        if document.anchor_id != anchor_id or document.slot != observed.slot:
            raise ComparatorCacheError
        views.append(_decode_view(document, by_id))
    return validate_cached(anchor_id, tuple(views))


def _decode_view(
    document: _ComparatorDocument,
    products: dict[str, ProductRecord],
) -> ComparatorView:
    missing = tuple(document.missing_reasons)
    if missing != tuple(sorted(set(missing), key=lambda item: item.encode("utf-8"))):
        raise ComparatorCacheError
    matched = tuple(
        MatchedQuantity(
            item.anchor_start,
            item.candidate_start,
            item.attribute_key,
            item.dimension,
            Decimal(item.value_similarity),
        )
        for item in document.matched_quantities
    )
    matched_order = tuple(
        sorted(
            matched,
            key=lambda item: (
                item.anchor_start,
                item.candidate_start,
                item.attribute_key,
                item.dimension,
            ),
        )
    )
    if matched != matched_order:
        raise ComparatorCacheError
    if document.candidate_id is None:
        if matched or document.option_role_observations or _has_scores(document.scores):
            raise ComparatorCacheError
        return ComparatorView(
            document.anchor_id,
            document.slot,
            "insufficient_candidates",
            None,
            None,
            (),
            missing,
        )
    candidate = products.get(document.candidate_id)
    if candidate is None:
        raise ComparatorCacheError
    roles = tuple(
        ObservedOptionRole(
            item.source_snapshot_id,
            item.source_row_key,
            item.delivery_request_key,
            str(item.item_sequence),
            str(item.change_sequence),
            item.role_raw,
            item.observed_at,
        )
        for item in document.option_role_observations
    )
    score = _decode_scores(document.scores)
    status: ComparatorStatus = (
        "ok" if score.score is not None else "no_comparison_evidence"
    )
    return ComparatorView(
        document.anchor_id,
        document.slot,
        status,
        replace(candidate, observed_option_roles=roles),
        score,
        matched,
        missing,
    )


def _decode_scores(scores: _Scores) -> ComparatorScores:
    return ComparatorScores(
        lexical=encoding.parse_decimal(scores.lexical),
        fuzzy=encoding.parse_decimal(scores.fuzzy),
        structured=encoding.parse_decimal(scores.structured),
        price=encoding.parse_decimal(scores.price),
        score=encoding.parse_decimal(scores.score),
        coverage=encoding.parse_decimal(scores.coverage),
    )


def _option_roles(roles: tuple[ObservedOptionRole, ...]) -> list[CacheJsonValue]:
    normalized = sorted(
        roles,
        key=lambda item: (
            item.source_snapshot_id,
            encoding.normalize_payload_text(item.source_row_key),
            encoding.normalize_payload_text(item.delivery_request_key),
            encoding.sequence_number(item.item_sequence),
            encoding.sequence_number(item.change_sequence),
        ),
    )
    return [
        {
            "change_sequence": encoding.sequence_number(item.change_sequence),
            "delivery_request_key": encoding.normalize_payload_text(
                item.delivery_request_key
            ),
            "item_sequence": encoding.sequence_number(item.item_sequence),
            "observed_at": encoding.normalize_payload_text(item.observed_at),
            "role_raw": encoding.normalize_payload_text(item.role_raw),
            "source_row_key": encoding.normalize_payload_text(item.source_row_key),
            "source_snapshot_id": item.source_snapshot_id,
        }
        for item in normalized
    ]


def _has_scores(scores: _Scores) -> bool:
    return any(
        value is not None
        for value in (
            scores.lexical,
            scores.fuzzy,
            scores.structured,
            scores.price,
            scores.score,
            scores.coverage,
        )
    )
