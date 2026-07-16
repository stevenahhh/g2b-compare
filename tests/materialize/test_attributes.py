from __future__ import annotations

from g2b_compare.materialize.attributes import (
    AttributeCoverageState,
    AttributeSourceRow,
    attribute_coverage,
    materialize_attributes,
)


def test_attribute_coverage_requires_complete_current_fingerprint_and_ttl() -> None:
    # Given
    states = (
        AttributeCoverageState(
            "A",
            "complete-nonempty",
            fingerprint_current=True,
            ttl_current=True,
            active=True,
        ),
        AttributeCoverageState(
            "B",
            "complete-empty",
            fingerprint_current=True,
            ttl_current=True,
            active=True,
        ),
        AttributeCoverageState(
            "C",
            "carried-forward",
            fingerprint_current=True,
            ttl_current=True,
            active=True,
        ),
        AttributeCoverageState(
            "D",
            "failed",
            fingerprint_current=True,
            ttl_current=True,
            active=True,
        ),
        AttributeCoverageState(
            "E",
            "complete-nonempty",
            fingerprint_current=False,
            ttl_current=True,
            active=True,
        ),
        AttributeCoverageState(
            "INACTIVE",
            "complete-nonempty",
            fingerprint_current=True,
            ttl_current=True,
            active=False,
        ),
    )

    # When
    coverage = attribute_coverage(states)

    # Then
    assert (coverage.covered_count, coverage.active_count, coverage.ratio) == (
        3,
        5,
        "0.6",
    )


def test_partial_attribute_rows_preserve_raw_and_deterministic_order() -> None:
    # Given
    rows = (
        AttributeSourceRow("zoom", 1, "A-2", " 줌 ", " 4배 ", None, None, "raw"),
        AttributeSourceRow(
            "resolution",
            0,
            "A-1",
            "해상도",
            "8MP",
            "8000000",
            "pixel",
            "parsed",
        ),
    )

    # When
    attributes = materialize_attributes(rows)

    # Then
    assert tuple((item.attribute_key, item.ordinal) for item in attributes) == (
        ("resolution", 0),
        ("zoom", 1),
    )
    assert attributes[1].raw_name == " 줌 "
