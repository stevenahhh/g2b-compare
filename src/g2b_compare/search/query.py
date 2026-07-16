"""Resolve exact candidate membership and compute TF-IDF-only scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

import numpy as np
from pydantic import TypeAdapter
from scipy.sparse import csr_matrix

from g2b_compare.db.sql import SqlRow, query
from g2b_compare.normalize.text import normalize_text

from .index_builder import char_vectorizer, word_vectorizer
from .index_format import decode_csr1
from .models import ProductRow

if TYPE_CHECKING:
    import sqlite3

VOCABULARY_ADAPTER: Final = TypeAdapter(dict[str, int])
PRODUCT_ROWS_ADAPTER: Final = TypeAdapter(tuple[ProductRow, ...])
DB_WRITE_AT_SEARCH: Final = "db-write-at-search"
NETWORK_AT_SEARCH: Final = "network-at-search"
NO_DETAIL_EXPANSION: Final = "no-detail-expansion"
WRONG_CATEGORY: Final = "wrong-category"


class IndexMembershipError(Exception):
    """Reject a search that would cross the exact B-tree membership boundary."""

    detail: str

    def __init__(self, detail: str) -> None:
        """Initialize one stable membership failure identifier."""
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


class SearchPurityError(Exception):
    """Report forbidden network activity or database mutation during search."""

    detail: str

    def __init__(self, detail: str) -> None:
        """Initialize one stable purity failure identifier."""
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class SearchProduct:
    """One active exact-membership product projection."""

    product_id: str
    category_key: tuple[str, str]
    product_name_raw: str
    product_name_key: str


@dataclass(frozen=True, slots=True)
class ExactMatchGroup:
    """Exact-name results grouped by their complete category tuple."""

    category_key: tuple[str, str]
    products: tuple[SearchProduct, ...]


@dataclass(frozen=True, slots=True)
class ScoreHit:
    """TF-IDF-only score over one global active product row."""

    product_id: str
    score: float


def resolve_exact(
    connection: sqlite3.Connection,
    materialization_id: int,
    raw_name: str,
    category_key: tuple[str, str] | None = None,
) -> tuple[ExactMatchGroup, ...]:
    """Resolve normalized name through the exact B-tree membership tuple."""
    name_key = normalize_text(raw_name).derived
    parameters: tuple[str | int, ...]
    if category_key is None:
        statement = """
            SELECT product_id, category_no, detail_category_no,
                   product_name_raw, product_name_key
            FROM search_membership
            WHERE materialization_id = ? AND product_name_key = ? AND active = 1
            ORDER BY category_no, detail_category_no, product_id
        """
        parameters = (materialization_id, name_key)
    else:
        statement = """
            SELECT product_id, category_no, detail_category_no,
                   product_name_raw, product_name_key
            FROM search_membership
            WHERE materialization_id = ? AND product_name_key = ? AND active = 1
              AND category_no = ? AND detail_category_no = ?
            ORDER BY product_id
        """
        parameters = (materialization_id, name_key, *category_key)
    rows = query(connection, statement, parameters).fetchall()
    if category_key is not None and not rows:
        _raise_category_miss(connection, materialization_id, name_key, category_key)
    products = tuple(_product(row) for row in rows)
    categories = tuple(
        sorted(
            {item.category_key for item in products},
            key=lambda item: (item[0].encode("utf-8"), item[1].encode("utf-8")),
        )
    )
    return tuple(
        ExactMatchGroup(
            category,
            tuple(item for item in products if item.category_key == category),
        )
        for category in categories
    )


def _raise_category_miss(
    connection: sqlite3.Connection,
    materialization_id: int,
    name_key: str,
    category_key: tuple[str, str],
) -> None:
    row = query(
        connection,
        """
        SELECT 1 FROM search_membership
        WHERE materialization_id = ? AND product_name_key = ? AND active = 1
          AND category_no = ? AND detail_category_no <> ? LIMIT 1
        """,
        (materialization_id, name_key, *category_key),
    ).fetchone()
    if row is not None:
        raise IndexMembershipError(NO_DETAIL_EXPANSION)
    raise IndexMembershipError(WRONG_CATEGORY)


def _product(row: SqlRow) -> SearchProduct:
    parsed = TypeAdapter(tuple[str, str, str, str, str]).validate_python(row)
    return SearchProduct(parsed[0], (parsed[1], parsed[2]), parsed[3], parsed[4])


def score_members(
    members: dict[str, bytes], raw_query: str
) -> tuple[ScoreHit, ...]:
    """Transform one query with stored IDF and dot against normalized CSR rows."""
    product_rows = PRODUCT_ROWS_ADAPTER.validate_json(members["product-rows.json"])
    product_ids = tuple(row.product_id for row in product_rows)
    normalized = normalize_text(raw_query)
    word_scores = _score_one(
        members,
        "word",
        normalized.tokens,
    )
    char_scores = _score_one(members, "char", normalized.derived)
    scores = tuple(
        (word + char) / 2.0
        for word, char in zip(word_scores, char_scores, strict=True)
    )
    return tuple(
        ScoreHit(product_id, score)
        for product_id, score in sorted(
            zip(product_ids, scores, strict=True),
            key=lambda item: (-item[1], item[0].encode("utf-8")),
        )
    )


def _score_one(
    members: dict[str, bytes], analyzer: str, query: tuple[str, ...] | str
) -> tuple[float, ...]:
    vocabulary = VOCABULARY_ADAPTER.validate_json(
        members[f"{analyzer}-vocabulary.json"]
    )
    decoded = decode_csr1(members[f"{analyzer}-matrix.csr1"])
    if not vocabulary:
        return tuple(0.0 for _ in range(decoded.rows))
    vectorizer = (
        word_vectorizer(vocabulary)
        if analyzer == "word"
        else char_vectorizer(vocabulary)
    )
    vectorizer.idf_ = np.frombuffer(members[f"{analyzer}-idf.f64le"], dtype="<f8")
    query_matrix = vectorizer.transform((query,))
    corpus = csr_matrix(
        (
            np.asarray(decoded.data, dtype=np.float64),
            np.asarray(decoded.indices, dtype=np.int32),
            np.asarray(decoded.indptr, dtype=np.int64),
        ),
        shape=(decoded.rows, decoded.cols),
    )
    values = (corpus @ query_matrix.T).toarray().reshape(-1)
    return tuple(float(value) for value in values)


def verify_search_purity(network_calls: int, database_changes: int) -> None:
    """Enforce the query-side zero-network and zero-write contract."""
    if network_calls:
        raise SearchPurityError(NETWORK_AT_SEARCH)
    if database_changes:
        raise SearchPurityError(DB_WRITE_AT_SEARCH)
