"""Lexical, fuzzy, structured, and price pair features."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from rapidfuzz import fuzz

from g2b_compare.search import index_builder
from g2b_compare.search.index_format import DecodedCSR, decode_csr1, serialize_csr1
from g2b_compare.search.models import IndexProduct

from .formula import log_distance, value_similarity
from .matching import MatchResult, match_specs

if TYPE_CHECKING:
    from g2b_compare.materialize.prices import ComparisonPrice

PAIR_FEATURE_CACHE_MAXSIZE: Final = 150_000
CONTEXT_FINGERPRINT_VERSION: Final = b"pair-features-context-v1\0"


def build_index(request: index_builder.IndexBuildRequest) -> index_builder.IndexBundle:
    """Expose the single request-scoped index construction seam."""
    return index_builder.build_index(request)


@dataclass(frozen=True, slots=True)
class PairFeatures:
    """All raw Ranking formula v1 components for one pair."""

    lexical: Decimal
    fuzzy: Decimal
    structured: Decimal | None
    price: Decimal | None
    price_distance: Decimal | None
    candidate_price_comparable: bool
    matching: MatchResult


@dataclass(frozen=True, slots=True)
class PreparedFeatureContext:
    """Request-scoped global lexical matrices shared by every candidate pair."""

    documents: tuple[str, ...]
    word_matrix: DecodedCSR
    char_matrix: DecodedCSR
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        """Bind documents and both matrices to one non-forgeable cache identity."""
        object.__setattr__(
            self,
            "fingerprint",
            _context_fingerprint(self.documents, self.word_matrix, self.char_matrix),
        )


@dataclass(frozen=True, slots=True)
class _ContextKey:
    fingerprint: str
    context: PreparedFeatureContext = field(compare=False, hash=False, repr=False)


def prepare_feature_context(corpus: tuple[str, ...]) -> PreparedFeatureContext:
    """Fit the exact v1 global corpus once for one ranking request."""
    products = tuple(
        IndexProduct(
            product_id=f"R-{index:08d}",
            category_key=("ranking", "v1"),
            product_name_raw="ranking",
            product_name_key="ranking",
            option_text=text,
            active=True,
        )
        for index, text in enumerate(corpus)
    )
    bundle = build_index(index_builder.IndexBuildRequest(0, "v1", "v1", "v1", products))
    return PreparedFeatureContext(
        documents=corpus,
        word_matrix=decode_csr1(bundle.member("word-matrix.csr1")),
        char_matrix=decode_csr1(bundle.member("char-matrix.csr1")),
    )


def pair_features(
    anchor_text: str,
    candidate_text: str,
    context: PreparedFeatureContext,
    anchor_price: ComparisonPrice,
    candidate_price: ComparisonPrice,
) -> PairFeatures:
    """Calculate all pair components against the same fitted text corpus."""
    return _cached_pair_features(
        _ContextKey(context.fingerprint, context),
        anchor_text,
        candidate_text,
        anchor_price,
        candidate_price,
    )


@lru_cache(maxsize=PAIR_FEATURE_CACHE_MAXSIZE)
def _cached_pair_features(
    context_key: _ContextKey,
    anchor_text: str,
    candidate_text: str,
    anchor_price: ComparisonPrice,
    candidate_price: ComparisonPrice,
) -> PairFeatures:
    context = context_key.context
    matching = match_specs(anchor_text, candidate_text)
    price, distance, comparable = _price_features(anchor_price, candidate_price)
    return PairFeatures(
        lexical_similarity(anchor_text, candidate_text, context),
        fuzzy_similarity(anchor_text, candidate_text),
        matching.similarity,
        price,
        distance,
        comparable,
        matching,
    )


def pair_features_cache_info() -> tuple[int, int, int, int]:
    """Return hits, misses, bound, and current entries for benchmark evidence."""
    info = _cached_pair_features.cache_info()
    return info.hits, info.misses, info.maxsize or 0, info.currsize


def clear_pair_features_cache() -> None:
    """Reset process-local pair memoization for deterministic measurements."""
    _cached_pair_features.cache_clear()


def _context_fingerprint(
    corpus: tuple[str, ...],
    word_matrix: DecodedCSR,
    char_matrix: DecodedCSR,
) -> str:
    digest = hashlib.sha256(CONTEXT_FINGERPRINT_VERSION)
    for document in corpus:
        encoded = document.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    for matrix in (word_matrix, char_matrix):
        encoded = serialize_csr1(
            matrix.rows,
            matrix.cols,
            matrix.indptr,
            matrix.indices,
            matrix.data,
        )
        digest.update(struct.pack(">Q", len(encoded)))
        digest.update(encoded)
    return digest.hexdigest()


def lexical_similarity(
    anchor_text: str,
    candidate_text: str,
    context: PreparedFeatureContext,
) -> Decimal:
    """Average exact v1 word and char TF-IDF cosine."""
    if not anchor_text or not candidate_text:
        return Decimal(0)
    anchor_row = context.documents.index(anchor_text)
    candidate_row = context.documents.index(candidate_text)
    word = Decimal(str(_row_dot(context.word_matrix, anchor_row, candidate_row)))
    char = Decimal(str(_row_dot(context.char_matrix, anchor_row, candidate_row)))
    return (word + char) / 2


def fuzzy_similarity(anchor_text: str, candidate_text: str) -> Decimal:
    """Average RapidFuzz token-set and token-sort similarities."""
    if not anchor_text or not candidate_text:
        return Decimal(0)
    score = (
        fuzz.token_set_ratio(anchor_text, candidate_text)
        + fuzz.token_sort_ratio(anchor_text, candidate_text)
    ) / 200
    return Decimal(str(score))


def _row_dot(matrix: DecodedCSR, left: int, right: int) -> float:
    left_values = _row_values(matrix, left)
    right_values = _row_values(matrix, right)
    return sum(
        value * right_values.get(feature, 0.0) for feature, value in left_values.items()
    )


def _row_values(matrix: DecodedCSR, row: int) -> dict[int, float]:
    start, end = matrix.indptr[row : row + 2]
    return {matrix.indices[index]: matrix.data[index] for index in range(start, end)}


def _price_features(
    anchor: ComparisonPrice, candidate: ComparisonPrice
) -> tuple[Decimal | None, Decimal | None, bool]:
    if not _positive_price(anchor):
        return None, None, False
    comparable = _positive_price(candidate) and anchor.unit_key == candidate.unit_key
    if not comparable:
        return Decimal(0), None, False
    if anchor.amount_won is None or candidate.amount_won is None:
        return Decimal(0), None, False
    anchor_amount = Decimal(anchor.amount_won)
    candidate_amount = Decimal(candidate.amount_won)
    return (
        value_similarity(anchor_amount, candidate_amount),
        log_distance(anchor_amount, candidate_amount),
        True,
    )


def _positive_price(price: ComparisonPrice) -> bool:
    return (
        price.active
        and price.amount_won is not None
        and price.amount_won > 0
        and price.unit_key is not None
    )
