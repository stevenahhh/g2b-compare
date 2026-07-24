"""Given raw text, verify source-preserving derived normalization."""

from hypothesis import given, settings
from hypothesis import strategies as st

from g2b_compare.normalize import normalize_text
from g2b_compare.normalize.text import normalize_search_text


@given(st.text())
@settings(derandomize=True, max_examples=100)
def test_raw_is_byte_stable_and_normalization_is_idempotent(raw: str) -> None:
    first = normalize_text(raw)
    second = normalize_text(first.derived)
    raw_bytes = raw.encode("utf-8")
    assert first.raw.encode("utf-8") == raw.encode("utf-8")
    for span in first.protected:
        assert raw_bytes[span.start_byte : span.end_byte].decode("utf-8") == span.raw
    assert second.derived == first.derived
    assert second.tokens == first.tokens


@given(
    st.text(alphabet=("가", "나", " ", "_", "🙂"), max_size=12),
    st.sampled_from(("8MP", "30fps", "10~20Hz", "3840\u00d72160")),
    st.text(alphabet=("다", "라", " ", "_", "🙂"), max_size=12),
)
@settings(derandomize=True, max_examples=100)
def test_tokenizer_protected_spans_are_utf8_byte_stable(
    prefix: str,
    quantity: str,
    suffix: str,
) -> None:
    raw = f"{prefix} {quantity} {suffix}"
    result = normalize_text(raw)
    raw_bytes = raw.encode("utf-8")
    quantity_span = next(span for span in result.protected if span.raw == quantity)
    assert (
        raw_bytes[quantity_span.start_byte : quantity_span.end_byte].decode("utf-8")
        == quantity
    )
    assert tuple(token.encode().decode() for token in result.tokens) == result.tokens


def test_nfkc_casefold_and_protected_source_order() -> None:
    result = normalize_text("  \uff21 영상 8MP  1,234.5kHz 끝 ")
    assert result.raw == "  \uff21 영상 8MP  1,234.5kHz 끝 "
    assert result.derived == "a 영상 8MP 1,234.5kHz 끝"
    assert result.tokens == ("a", "영상", "8MP", "1,234.5kHz", "끝")
    assert [(span.start_byte, span.end_byte) for span in result.protected] == [
        (13, 16),
        (18, 28),
    ]


def test_search_aliases_link_megapixels_and_optical_zoom() -> None:
    document = normalize_search_text(
        "보조카메라:화소:2MP/최대줌:Optical x4",
    )
    query = normalize_search_text("200만화소 4배줌")

    assert all(term in document for term in query.split())
