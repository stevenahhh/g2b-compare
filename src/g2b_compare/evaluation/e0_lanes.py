"""Strict E0 candidate-lane scoring, deduplication, and backfill."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.features import pair_features, prepare_feature_context
from g2b_compare.ranking.formula import FormulaInput, score_formula

from .e0_models import E0ExportBlocked, E0Product, Lane, ReleaseIdentity

if TYPE_CHECKING:
    from collections.abc import Callable

    from g2b_compare.db.hashes import JsonValue
    from g2b_compare.ranking.explain import ScoreBreakdown

PAIR_COUNT = 10


@dataclass(frozen=True, slots=True)
class PairMetric:
    """Quantized lane ordering values for one exact-pool pair."""

    product: E0Product
    lexical: Decimal
    structured: Decimal | None
    coverage: Decimal | None
    price_distance: Decimal | None
    structured_evidence: Decimal
    price_comparable: bool


@dataclass(frozen=True, slots=True)
class TakeRequest:
    """One ordered lane quota and value projection."""

    candidates: list[PairMetric]
    lane: Lane
    quota: int
    value: Callable[[PairMetric], str]


@dataclass(frozen=True, slots=True)
class PoolBuildContext:
    """Frozen release and selection facts shared by all anchors."""

    exact_pools: dict[tuple[str, str, str], tuple[E0Product, ...]]
    splits: dict[tuple[str, str], str]
    anchor_strata: dict[str, str]
    identity: ReleaseIdentity
    seed: str


def build_pool_rows(
    anchors: tuple[E0Product, ...],
    context: PoolBuildContext,
) -> tuple[dict[str, JsonValue], ...]:
    """Build exact ten unique candidate rows per selected anchor."""
    rows: list[dict[str, JsonValue]] = []
    for anchor in anchors:
        pool_key = (*anchor.category_tuple, anchor.product_name_key)
        candidates = tuple(
            product
            for product in context.exact_pools[pool_key]
            if product.product_id != anchor.product_id
        )
        metrics = _metrics(anchor, candidates)
        selections = _select(anchor, metrics, context.seed)
        if len(selections) != PAIR_COUNT:
            detail = f"anchor {anchor.product_id} lacks ten candidates"
            raise E0ExportBlocked(detail)
        for lane, metric, lane_value in selections:
            rows.append(
                {
                    "anchor_id": anchor.product_id,
                    "anchor_stratum": context.anchor_strata[anchor.product_id],
                    "candidate_id": metric.product.product_id,
                    "category_tuple": {
                        "category_no": anchor.category_no,
                        "detail_category_no": anchor.detail_category_no,
                    },
                    "exact_name_key": anchor.product_name_key,
                    "lane": lane,
                    "lane_value": lane_value,
                    "ranking_version": context.identity.ranking_version,
                    "source_index_sha": context.identity.index_artifact_sha,
                    "source_materialization_sha": context.identity.materialization_sha,
                    "source_release_bundle_sha": context.identity.release_bundle_sha,
                    "split": context.splits[anchor.category_tuple],
                }
            )
    return tuple(rows)


def _metrics(
    anchor: E0Product, candidates: tuple[E0Product, ...]
) -> tuple[PairMetric, ...]:
    context = prepare_feature_context(
        (anchor.option_text, *(candidate.option_text for candidate in candidates))
    )
    anchor_price = _price(anchor)
    output: list[PairMetric] = []
    for candidate in candidates:
        features = pair_features(
            anchor.option_text,
            candidate.option_text,
            context,
            anchor_price,
            _price(candidate),
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
                anchor_price_active=_price_active(anchor),
                candidate_price_comparable=features.candidate_price_comparable,
            )
        )
        output.append(_metric(candidate, explanation))
    return tuple(output)


def _metric(product: E0Product, score: ScoreBreakdown) -> PairMetric:
    return PairMetric(
        product=product,
        lexical=score.lexical,
        structured=score.structured,
        coverage=score.coverage,
        price_distance=score.price_distance,
        structured_evidence=score.evidence.structured,
        price_comparable=bool(score.evidence.price),
    )


def _select(
    anchor: E0Product, metrics: tuple[PairMetric, ...], seed: str
) -> tuple[tuple[Lane, PairMetric, str], ...]:
    selected: list[tuple[Lane, PairMetric, str]] = []
    seen: set[str] = set()
    lexical = sorted(
        (item for item in metrics if anchor.option_text and item.product.option_text),
        key=lambda item: (-item.lexical, item.product.product_id),
    )
    _take(
        selected,
        seen,
        TakeRequest(lexical, "lexical", 3, lambda item: _decimal(item.lexical)),
    )
    structured = sorted(
        (
            item
            for item in metrics
            if item.structured is not None and item.structured_evidence > 0
        ),
        key=lambda item: (
            -(item.structured or Decimal(0)),
            -(item.coverage or Decimal(0)),
            item.product.product_id,
        ),
    )
    _take(
        selected,
        seen,
        TakeRequest(
            structured,
            "structured",
            3,
            lambda item: _decimal(item.structured or Decimal(0)),
        ),
    )
    price = sorted(
        (item for item in metrics if item.price_comparable),
        key=lambda item: (
            item.price_distance is None,
            item.price_distance or Decimal(0),
            item.product.product_id,
        ),
    )
    _take(
        selected,
        seen,
        TakeRequest(
            price,
            "price",
            2,
            lambda item: _decimal(item.price_distance or Decimal(0)),
        ),
    )
    hashed = sorted(
        metrics,
        key=lambda item: (
            _pair_hash(seed, anchor.product_id, item.product.product_id),
            item.product.product_id,
        ),
    )
    _take(
        selected,
        seen,
        TakeRequest(
            hashed,
            "hash",
            2,
            lambda item: _pair_hash(seed, anchor.product_id, item.product.product_id),
        ),
    )
    _take(
        selected,
        seen,
        TakeRequest(
            hashed,
            "backfill",
            PAIR_COUNT - len(selected),
            lambda item: _pair_hash(seed, anchor.product_id, item.product.product_id),
        ),
    )
    return tuple(selected)


def _take(
    selected: list[tuple[Lane, PairMetric, str]],
    seen: set[str],
    request: TakeRequest,
) -> None:
    if request.quota <= 0:
        return
    added = 0
    for item in request.candidates:
        if item.product.product_id in seen:
            continue
        selected.append((request.lane, item, request.value(item)))
        seen.add(item.product.product_id)
        added += 1
        if added == request.quota:
            return


def _price(product: E0Product) -> ComparisonPrice:
    active = _price_active(product)
    return ComparisonPrice(active, product.price_won, product.price_unit, None, None)


def _price_active(product: E0Product) -> bool:
    return (
        product.price_won is not None
        and product.price_won > 0
        and product.price_unit is not None
    )


def _decimal(value: Decimal) -> str:
    return format(value, ".6f")


def _pair_hash(seed: str, anchor_id: str, candidate_id: str) -> str:
    payload = f"{seed}|{anchor_id}|{candidate_id}".encode()
    return hashlib.sha256(payload).hexdigest()
