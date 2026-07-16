from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from g2b_compare.materialize.attributes import (
    AttributeSourceRow,
    materialize_attributes,
)
from g2b_compare.materialize.options import FallbackText, build_option_text


def test_option_text_fixture_is_byte_exact_and_repeatable() -> None:
    # Given
    fixture = TypeAdapter(dict[str, str]).validate_json(
        Path("tests/fixtures/materialize/option-text-v1.json").read_bytes()
    )
    rows = (
        AttributeSourceRow("zoom", 0, "A-2", "줌", "4 배", None, None, "raw"),
        AttributeSourceRow(
            "resolution",
            1,
            "A-1",
            " 해상도 ",
            " ８００만 화소 ",
            None,
            None,
            "raw",
        ),
    )
    fallbacks = FallbackText(" \uff18MP ", "8MP", "방수")

    # When
    first = build_option_text(materialize_attributes(rows), fallbacks)
    replay = build_option_text(materialize_attributes(tuple(reversed(rows))), fallbacks)

    # Then
    assert first.text == fixture["output"]
    assert first.utf8_sha256 == fixture["sha256"]
    assert first == replay


def test_option_text_skips_empty_and_deduplicates_exact_segments() -> None:
    # Given
    rows = (
        AttributeSourceRow("a", 0, "1", "모델", " X-1 ", None, None, "raw"),
        AttributeSourceRow("a", 1, "2", "모델", "X-1", None, None, "raw"),
        AttributeSourceRow("b", 0, "3", "", "", None, None, "raw"),
    )

    # When
    result = build_option_text(
        materialize_attributes(rows),
        FallbackText("", " 세부 ", ""),
    )

    # Then
    assert result.segments == ("attr:모델=x-1", "detail:세부")
    assert result.text == "attr:모델=x-1 | detail:세부"
    assert " | " in result.text


def test_all_empty_option_text_is_empty() -> None:
    # Given / When
    result = build_option_text((), FallbackText("", "  ", ""))

    # Then
    assert (result.segments, result.text) == ((), "")
    assert json.dumps(result.text) == '""'
