from __future__ import annotations

from decimal import Decimal

from g2b_compare.ranking.matching import context_is_eligible, match_specs


def test_800_man_pixels_matches_8mp_but_resolution_does_not() -> None:
    equivalent = match_specs("attr:화소=800만화소", "attr:화소=8MP")
    resolution = match_specs("attr:화소=800만화소", "3840x2160")

    assert equivalent.similarity == 1.0
    assert equivalent.matched_anchor_count == 1
    assert resolution.matched_anchor_count == 0


def test_matching_is_one_to_one() -> None:
    result = match_specs("8MP 8MP", "8MP")

    assert result.anchor_count == 2
    assert result.matched_anchor_count == 1
    assert result.similarity == 0.5


def test_unknown_attribute_context_boundary_is_inclusive() -> None:
    assert context_is_eligible(Decimal("0.750000"))
    assert not context_is_eligible(Decimal("0.749999"))


def test_relation_shape_and_range_are_strict() -> None:
    same_range = match_specs("10~20cm", "10~20cm")
    different_relation = match_specs("10cm 이상", "10cm 이하")

    assert same_range.similarity == 1
    assert different_relation.matched_anchor_count == 0
