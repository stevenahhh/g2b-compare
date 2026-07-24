from __future__ import annotations

from dataclasses import replace

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.features import (
    clear_pair_features_cache,
    pair_features,
    pair_features_cache_info,
    prepare_feature_context,
)
from g2b_compare.ranking.formula import value_similarity_cache_maxsize
from g2b_compare.ranking.matching_context import matching_cache_maxsizes
from g2b_compare.ranking.topk import (
    RankableProduct,
    prepare_top_three_context,
    top_three,
)


def _price(amount: int) -> ComparisonPrice:
    return ComparisonPrice(
        active=True,
        amount_won=amount,
        unit_key="대",
        offer_key=("offer", str(amount)),
        reason=None,
    )


def test_pair_features_cache_preserves_exact_value_and_hits() -> None:
    clear_pair_features_cache()
    context = prepare_feature_context(("8MP 30fps", "8MP 15fps"))

    first = pair_features("8MP 30fps", "8MP 15fps", context, _price(10), _price(11))
    second = pair_features("8MP 30fps", "8MP 15fps", context, _price(10), _price(11))

    assert first == second
    assert pair_features_cache_info() == (1, 1, 150_000, 1)


def test_pair_features_cache_isolates_different_contexts() -> None:
    clear_pair_features_cache()
    first_context = prepare_feature_context(("8MP 30fps", "8MP 15fps", "4MP"))
    second_context = prepare_feature_context(("8MP 30fps", "8MP 15fps", "16MP"))

    first = pair_features(
        "8MP 30fps",
        "8MP 15fps",
        first_context,
        _price(10),
        _price(11),
    )
    second = pair_features(
        "8MP 30fps",
        "8MP 15fps",
        second_context,
        _price(10),
        _price(11),
    )

    assert first_context.fingerprint != second_context.fingerprint
    assert first is not second
    assert pair_features_cache_info() == (0, 2, 150_000, 2)


def test_pair_features_cache_rejects_same_document_fingerprint_with_matrix_drift() -> (
    None
):
    clear_pair_features_cache()
    context = prepare_feature_context(("8MP 30fps", "8MP 15fps"))
    drifted = replace(
        context,
        word_matrix=replace(
            context.word_matrix,
            data=tuple(value / 2 for value in context.word_matrix.data),
        ),
    )

    first = pair_features("8MP 30fps", "8MP 15fps", context, _price(10), _price(11))
    second = pair_features("8MP 30fps", "8MP 15fps", drifted, _price(10), _price(11))

    assert context.fingerprint != drifted.fingerprint
    assert first is not second
    assert pair_features_cache_info() == (0, 2, 150_000, 2)


def test_shared_top_three_context_excludes_ineligible_products_exactly() -> None:
    anchor = _rankable("A", "8MP", active=True)
    eligible = _rankable("B", "4MP", active=True)
    inactive = _rankable("C", "INACTIVE", active=False)
    other = _rankable("D", "OTHER", active=True, category=("99", "9999"))
    candidates = (anchor, eligible, inactive, other)
    shared = prepare_top_three_context(candidates)

    baseline = top_three(anchor, candidates)
    provided = top_three(anchor, candidates, shared)
    other_baseline = top_three(other, candidates)
    other_provided = top_three(other, candidates, shared)

    assert shared.documents == ("8MP", "4MP")
    assert provided == baseline
    assert other_provided == other_baseline


def test_all_ranking_lrus_enforce_the_same_eviction_bound() -> None:
    assert value_similarity_cache_maxsize() == 150_000
    assert matching_cache_maxsizes() == (150_000, 150_000)


def _rankable(
    product_id: str,
    option_text: str,
    *,
    active: bool,
    category: tuple[str, str] = ("45", "4512"),
) -> RankableProduct:
    return RankableProduct(
        product_id,
        category,
        "영상감시장치",
        option_text,
        active,
        _price(10),
    )
