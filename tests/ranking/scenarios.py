from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.features import pair_features, prepare_feature_context
from g2b_compare.ranking.formula import FormulaInput, score_formula
from g2b_compare.ranking.matching import (
    context_is_eligible,
    extract_context_specs,
    match_specs,
)
from g2b_compare.ranking.topk import RankableProduct, top_three

if TYPE_CHECKING:
    from collections.abc import Callable

SCENARIOS: Final = (
    "hand-vector-mismatch",
    "context-window-left",
    "context-window-right",
    "context-below-075",
    "coverage-L",
    "coverage-F",
    "coverage-U-partial",
    "coverage-P",
    "price-tie-quantization",
    "resolution-not-mp",
    "dimension-repeat",
    "range-relation",
    "incompatible-dimension",
    "missing-price",
    "zero-price",
    "mixed-unit",
    "d-zero",
    "exact-tie",
    "duplicate-product",
    "candidate-deletion",
)


@dataclass(frozen=True, slots=True)
class HappyResult:
    identifiers: tuple[str, ...]
    score: Decimal
    coverage: Decimal
    exact_slots: int


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


def price(amount: int = 1_000_000, unit: str = "대") -> ComparisonPrice:
    return ComparisonPrice(
        active=True,
        amount_won=amount,
        unit_key=unit,
        offer_key=("op", str(amount)),
        reason=None,
    )


def missing(reason: str = "missing-price") -> ComparisonPrice:
    return ComparisonPrice(
        active=False,
        amount_won=None,
        unit_key=None,
        offer_key=None,
        reason=reason,
    )


def product(
    product_id: str,
    option: str = "800만화소 실외형",
    *,
    comparison_price: ComparisonPrice | None = None,
) -> RankableProduct:
    return RankableProduct(
        product_id=product_id,
        category_key=("4512", "451215"),
        product_name_key="영상감시장치",
        option_text=option,
        active=True,
        price=comparison_price or price(),
    )


def run_happy() -> HappyResult:
    slots = top_three(
        product("A", "attr:화소=800만화소 | spec:실외형"),
        (
            product("C", "8MP 실내형", comparison_price=price(1_100_000)),
            product("B", "8MP 실외형"),
            product("D", "4MP 실외형", comparison_price=price(2_000_000)),
        ),
    )
    first = slots[0].explanation
    assert first is not None
    assert first.score is not None
    assert first.coverage is not None
    return HappyResult(
        tuple(slot.comparator.product_id for slot in slots if slot.comparator),
        first.score,
        first.coverage,
        len(slots),
    )


def observe_failure(scenario: str) -> FailureObservation:
    RUNNERS[scenario]()
    return FailureObservation("RankingObservation", scenario)


def _formula() -> FormulaInput:
    return FormulaInput(
        lexical=Decimal("0.8"),
        fuzzy=Decimal("0.75"),
        structured=Decimal(1),
        price=Decimal(1),
        price_distance=Decimal(0),
        anchor_option_present=True,
        candidate_option_present=True,
        anchor_spec_count=1,
        matched_anchor_count=1,
        anchor_price_active=True,
        candidate_price_comparable=True,
    )


def _hand_vector() -> None:
    assert Path("tests/fixtures/ranking/hand-calculated-v1.json").is_file()
    assert score_formula(_formula()).score == Decimal("0.880000")


def _context_left() -> None:
    spec = extract_context_specs("a b c 8MP d e f g")[0]
    assert spec.context == "a b c d e f"


def _context_right() -> None:
    spec = extract_context_specs("z a b c 8MP d e f")[0]
    assert spec.context == "a b c d e f"


def _context_below() -> None:
    assert not context_is_eligible(Decimal("0.749999"))


def _coverage_l() -> None:
    source = replace(
        _formula(),
        lexical=Decimal(0),
        fuzzy=Decimal(0),
        candidate_option_present=False,
    )
    assert score_formula(source).evidence.lexical == 0


def _coverage_f() -> None:
    source = replace(
        _formula(),
        lexical=Decimal(0),
        fuzzy=Decimal(0),
        candidate_option_present=False,
    )
    assert score_formula(source).evidence.fuzzy == 0


def _coverage_u() -> None:
    result = score_formula(
        replace(
            _formula(),
            structured=Decimal("0.5"),
            anchor_spec_count=2,
            matched_anchor_count=1,
        )
    )
    assert result.evidence.structured == Decimal("0.5")
    assert result.coverage is not None
    assert result.coverage < 1


def _coverage_p() -> None:
    source = replace(
        _formula(),
        price=Decimal(0),
        price_distance=None,
        candidate_price_comparable=False,
    )
    assert score_formula(source).evidence.price == 0


def _price_tie() -> None:
    slots = top_three(
        product("A"),
        (
            product("C", comparison_price=price(1_000_001)),
            product("B", comparison_price=price(999_999)),
        ),
    )
    assert slots[0].comparator is not None
    assert slots[0].comparator.product_id == "B"


def _resolution() -> None:
    assert match_specs("800만화소", "3840x2160").matched_anchor_count == 0


def _dimension_repeat() -> None:
    assert match_specs("8MP 8MP", "8MP").matched_anchor_count == 1


def _range_relation() -> None:
    assert match_specs("10~20cm", "10~20cm").similarity == 1
    assert match_specs("10cm 이상", "10cm 이하").matched_anchor_count == 0


def _incompatible_dimension() -> None:
    assert match_specs("8MP", "8GB").matched_anchor_count == 0


def _price_case(candidate: ComparisonPrice) -> None:
    context = prepare_feature_context(("8MP", "8MP"))
    result = pair_features("8MP", "8MP", context, price(), candidate)
    assert result.price == 0
    assert result.price_distance is None


def _d_zero() -> None:
    slots = top_three(
        product("A", "", comparison_price=missing()),
        (product("B", "", comparison_price=missing()),),
    )
    assert slots[0].status == "no_comparison_evidence"


def _exact_tie() -> None:
    slots = top_three(product("A"), (product("C"), product("B")))
    assert slots[0].comparator is not None
    assert slots[0].comparator.product_id == "B"


def _duplicate() -> None:
    slots = top_three(product("A"), (product("B"), product("B")))
    assert slots[0].comparator is not None
    assert slots[1].comparator is None


def _deletion() -> None:
    anchor = product("A")
    full = top_three(anchor, (product("B"),))[0].explanation
    sparse = top_three(anchor, (product("B", ""),))[0].explanation
    assert full is not None
    assert sparse is not None
    assert full.score is not None
    assert sparse.score is not None
    assert full.coverage is not None
    assert sparse.coverage is not None
    assert sparse.score <= full.score
    assert sparse.coverage <= full.coverage


RUNNERS: Final[dict[str, Callable[[], None]]] = {
    "hand-vector-mismatch": _hand_vector,
    "context-window-left": _context_left,
    "context-window-right": _context_right,
    "context-below-075": _context_below,
    "coverage-L": _coverage_l,
    "coverage-F": _coverage_f,
    "coverage-U-partial": _coverage_u,
    "coverage-P": _coverage_p,
    "price-tie-quantization": _price_tie,
    "resolution-not-mp": _resolution,
    "dimension-repeat": _dimension_repeat,
    "range-relation": _range_relation,
    "incompatible-dimension": _incompatible_dimension,
    "missing-price": lambda: _price_case(missing()),
    "zero-price": lambda: _price_case(missing("zero-price")),
    "mixed-unit": lambda: _price_case(price(unit="세트")),
    "d-zero": _d_zero,
    "exact-tie": _exact_tie,
    "duplicate-product": _duplicate,
    "candidate-deletion": _deletion,
}
