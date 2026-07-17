"""Build request and product-anchored comparisons from Ranking formula v1."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from g2b_compare.ranking.features import (
    PreparedFeatureContext,
    pair_features,
    prepare_feature_context,
)
from g2b_compare.ranking.formula import FormulaInput, quantize_score, score_formula
from g2b_compare.ranking.matching import MatchResult, match_specs
from g2b_compare.ranking.topk import (
    ComparisonSlot,
    RankableProduct,
    top_three,
)

if TYPE_CHECKING:
    from g2b_compare.ranking.explain import ScoreBreakdown

from .comparator_models import (
    ComparatorCacheError,
    ComparatorScores,
    ComparatorStatus,
    ComparatorView,
    CuratedRelation,
    MatchedQuantity,
    ObservedOptionRole,
    ProductRecord,
    ScoredRecord,
)

__all__ = [
    "ComparatorCacheError",
    "ComparatorScores",
    "ComparatorStatus",
    "ComparatorView",
    "CuratedRelation",
    "MatchedQuantity",
    "ObservedOptionRole",
    "ProductRecord",
    "ScoredRecord",
    "build_comparators",
    "compare_product",
    "score_pool",
    "validate_cached",
]

COMPARATOR_SLOT_COUNT: Final = 3


def build_comparators(
    anchor: RankableProduct,
    candidates: tuple[RankableProduct, ...],
) -> tuple[ComparisonSlot, ComparisonSlot, ComparisonSlot]:
    """Return exactly three tolerance-free Ranking-v1 slots."""
    return top_three(anchor, candidates)


def score_pool(
    anchor: RankableProduct,
    candidates: tuple[ProductRecord, ...],
) -> tuple[ScoredRecord, ...]:
    """Score every exact-pool candidate in one request-scoped feature context."""
    if not candidates:
        return ()
    context = prepare_feature_context(
        (anchor.option_text, *(item.rankable.option_text for item in candidates))
    )
    return tuple(_score_record(anchor, item, context) for item in candidates)


def compare_product(
    anchor: ProductRecord,
    candidates: tuple[ProductRecord, ...],
) -> tuple[ComparatorView, ComparatorView, ComparatorView]:
    """Anchor Ranking v1 on one product and attach release-pinned provenance."""
    slots = top_three(anchor.rankable, tuple(item.rankable for item in candidates))
    by_id = {item.rankable.product_id: item for item in candidates}
    views = tuple(_slot_view(anchor, slot, by_id) for slot in slots)
    return views[0], views[1], views[2]


def validate_cached(
    anchor_id: str,
    slots: tuple[ComparatorView, ...],
) -> tuple[ComparatorView, ComparatorView, ComparatorView]:
    """Accept only an exact, ordered, unique three-slot cache payload."""
    if len(slots) != COMPARATOR_SLOT_COUNT or tuple(item.rank for item in slots) != (
        1,
        2,
        3,
    ):
        raise ComparatorCacheError
    if any(item.anchor_id != anchor_id for item in slots):
        raise ComparatorCacheError
    candidate_ids = tuple(
        item.candidate.rankable.product_id
        for item in slots
        if item.candidate is not None
    )
    if len(candidate_ids) != len(frozenset(candidate_ids)):
        raise ComparatorCacheError
    return slots[0], slots[1], slots[2]


def _score_record(
    anchor: RankableProduct,
    candidate: ProductRecord,
    context: PreparedFeatureContext,
) -> ScoredRecord:
    features = pair_features(
        anchor.option_text,
        candidate.rankable.option_text,
        context,
        anchor.price,
        candidate.rankable.price,
    )
    scores = score_formula(
        FormulaInput(
            lexical=features.lexical,
            fuzzy=features.fuzzy,
            structured=features.structured,
            price=features.price,
            price_distance=features.price_distance,
            anchor_option_present=bool(anchor.option_text),
            candidate_option_present=bool(candidate.rankable.option_text),
            anchor_spec_count=features.matching.anchor_count,
            matched_anchor_count=features.matching.matched_anchor_count,
            anchor_price_active=_positive_price(anchor),
            candidate_price_comparable=features.candidate_price_comparable,
        )
    )
    return ScoredRecord(
        candidate,
        scores,
        _matched(features.matching),
        _missing(anchor, candidate.rankable, scores),
    )


def _slot_view(
    anchor: ProductRecord,
    slot: ComparisonSlot,
    candidates: dict[str, ProductRecord],
) -> ComparatorView:
    if slot.comparator is None or slot.explanation is None:
        return ComparatorView(
            anchor.rankable.product_id,
            slot.rank,
            _status(slot.status),
            None,
            None,
            (),
            (slot.status,),
        )
    candidate = candidates[slot.comparator.product_id]
    matching = match_specs(anchor.rankable.option_text, candidate.rankable.option_text)
    return ComparatorView(
        anchor.rankable.product_id,
        slot.rank,
        _status(slot.status),
        candidate,
        _score_view(slot.explanation),
        _matched(matching),
        _missing(anchor.rankable, candidate.rankable, slot.explanation),
    )


def _matched(result: MatchResult) -> tuple[MatchedQuantity, ...]:
    return tuple(
        MatchedQuantity(
            item.anchor.semantic.source_span.start_byte,
            item.candidate.semantic.source_span.start_byte,
            item.anchor.semantic.attribute_key,
            item.anchor.semantic.dimension,
            quantize_score(item.weight),
        )
        for item in result.pairs
    )


def _missing(
    anchor: RankableProduct,
    candidate: RankableProduct,
    scores: ScoreBreakdown,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if scores.score is None:
        reasons.add("no_comparison_evidence")
    if not candidate.option_text:
        reasons.add("missing_candidate_option_text")
    if _positive_price(anchor) and not scores.evidence.price:
        reasons.add(candidate.price.reason or "incompatible_price")
    if scores.activity.structured and scores.evidence.structured < 1:
        reasons.add("partial_structured_match")
    return tuple(sorted(reasons, key=lambda item: item.encode("utf-8")))


def _positive_price(product: RankableProduct) -> bool:
    price = product.price
    return bool(
        price.active
        and price.amount_won is not None
        and price.amount_won > 0
        and price.unit_key is not None
    )


def _score_view(scores: ScoreBreakdown) -> ComparatorScores:
    return ComparatorScores(
        lexical=scores.lexical,
        fuzzy=scores.fuzzy,
        structured=scores.structured,
        price=scores.price,
        score=scores.score,
        coverage=scores.coverage,
    )


def _status(value: str) -> ComparatorStatus:
    if value == "ok":
        return "ok"
    if value == "no_comparison_evidence":
        return "no_comparison_evidence"
    if value == "insufficient_candidates":
        return "insufficient_candidates"
    raise ComparatorCacheError
