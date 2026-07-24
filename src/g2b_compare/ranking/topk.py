"""Filter, score, deduplicate, and return exactly three slots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .features import PreparedFeatureContext, pair_features, prepare_feature_context
from .formula import FormulaInput, score_formula

TOP_K = 3

if TYPE_CHECKING:
    from g2b_compare.materialize.prices import ComparisonPrice

    from .explain import ScoreBreakdown


@dataclass(frozen=True, slots=True)
class RankableProduct:
    """Canonical product fields required by Ranking formula v1."""

    product_id: str
    category_key: tuple[str, str]
    product_name_key: str
    option_text: str
    active: bool
    price: ComparisonPrice
    contract_corp_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedComparator:
    """One eligible product with its auditable score breakdown."""

    product: RankableProduct
    explanation: ScoreBreakdown


@dataclass(frozen=True, slots=True)
class ComparisonSlot:
    """One of the three stable response positions."""

    rank: int
    comparator: RankableProduct | None
    status: str
    explanation: ScoreBreakdown | None
    same_corp_as_higher_slot: bool = False


def top_three(
    anchor: RankableProduct,
    candidates: tuple[RankableProduct, ...],
    context: PreparedFeatureContext | None = None,
) -> tuple[ComparisonSlot, ComparisonSlot, ComparisonSlot]:
    """Return the exact-pool top three, filling only genuine shortages."""
    eligible = _eligible_unique(anchor, candidates)
    corpus = tuple(
        item.option_text for item in sorted((anchor, *eligible), key=_dedupe_key)
    )
    if not eligible:
        return (
            ComparisonSlot(1, None, "insufficient_candidates", None),
            ComparisonSlot(2, None, "insufficient_candidates", None),
            ComparisonSlot(3, None, "insufficient_candidates", None),
        )
    selected_context = (
        context
        if context is not None and context.documents == corpus
        else prepare_feature_context(corpus)
    )
    ranked = tuple(
        _score(anchor, candidate, selected_context) for candidate in eligible
    )
    ordered = sorted(ranked, key=_sort_key)
    selected = _diverse_order(ordered)
    slots: list[ComparisonSlot] = []
    for rank in range(1, 4):
        if rank > len(selected):
            slots.append(ComparisonSlot(rank, None, "insufficient_candidates", None))
            continue
        item, same_corp = selected[rank - 1]
        status = "no_comparison_evidence" if item.explanation.score is None else "ok"
        slots.append(
            ComparisonSlot(rank, item.product, status, item.explanation, same_corp)
        )
    return slots[0], slots[1], slots[2]


def prepare_top_three_context(
    candidates: tuple[RankableProduct, ...],
) -> PreparedFeatureContext:
    """Fit one comparator pool for reuse across every product anchor."""
    anchor = candidates[0]
    eligible = _eligible_unique(anchor, candidates)
    corpus = tuple(
        item.option_text for item in sorted((anchor, *eligible), key=_dedupe_key)
    )
    return prepare_feature_context(corpus)


def _eligible_unique(
    anchor: RankableProduct, candidates: tuple[RankableProduct, ...]
) -> tuple[RankableProduct, ...]:
    exact = (
        item
        for item in candidates
        if item.active
        and item.product_id != anchor.product_id
        and item.category_key == anchor.category_key
        and item.product_name_key == anchor.product_name_key
    )
    ordered = sorted(exact, key=_dedupe_key)
    unique: dict[str, RankableProduct] = {}
    for item in ordered:
        _ = unique.setdefault(item.product_id, item)
    return tuple(unique.values())


def _dedupe_key(product: RankableProduct) -> tuple[str, str, str, int, str]:
    price = product.price.amount_won if product.price.amount_won is not None else -1
    unit = product.price.unit_key or ""
    return (
        product.product_id,
        product.option_text,
        str(product.price.active),
        price,
        unit,
    )


def _score(
    anchor: RankableProduct,
    candidate: RankableProduct,
    context: PreparedFeatureContext,
) -> RankedComparator:
    features = pair_features(
        anchor.option_text,
        candidate.option_text,
        context,
        anchor.price,
        candidate.price,
    )
    explanation = score_formula(
        FormulaInput(
            lexical=features.lexical,
            fuzzy=features.fuzzy,
            structured=features.structured,
            price=features.price,
            price_distance=features.price_distance,
            anchor_option_present=bool(anchor.option_text),
            candidate_option_present=bool(candidate.option_text),
            anchor_spec_count=features.matching.anchor_count,
            matched_anchor_count=features.matching.matched_anchor_count,
            anchor_price_active=_anchor_price_active(anchor.price),
            candidate_price_comparable=features.candidate_price_comparable,
        )
    )
    return RankedComparator(candidate, explanation)


def _diverse_order(
    ordered: list[RankedComparator],
) -> tuple[tuple[RankedComparator, bool], ...]:
    selected: list[tuple[RankedComparator, bool]] = []
    deferred: list[RankedComparator] = []
    corp_ids: set[str] = set()
    for item in ordered:
        candidate_ids = set(item.product.contract_corp_ids)
        if candidate_ids and candidate_ids.intersection(corp_ids):
            deferred.append(item)
            continue
        selected.append((item, False))
        corp_ids.update(candidate_ids)
        if len(selected) == TOP_K:
            return tuple(selected)
    for item in deferred:
        selected.append((item, True))
        if len(selected) == TOP_K:
            break
    return tuple(selected)


def _anchor_price_active(price: ComparisonPrice) -> bool:
    return (
        price.active
        and price.amount_won is not None
        and price.amount_won > 0
        and price.unit_key is not None
    )


def _sort_key(
    item: RankedComparator,
) -> tuple[
    bool,
    Decimal,
    bool,
    Decimal,
    Decimal,
    Decimal,
    bool,
    Decimal,
    str,
]:
    explanation = item.explanation
    return (
        explanation.score is None,
        -(explanation.score or Decimal(0)),
        explanation.structured is None,
        -(explanation.structured or Decimal(0)),
        -explanation.lexical,
        -explanation.fuzzy,
        explanation.price_distance is None,
        explanation.price_distance or Decimal(0),
        item.product.product_id,
    )
