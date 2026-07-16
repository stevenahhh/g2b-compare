"""Fit byte-stable word and character TF-IDF artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.normalize.text import normalize_text

from .index_format import (
    EXACT_MEMBER_NAMES,
    IndexFormatError,
    artifact_sha256,
    serialize_csr1,
    validate_bundle,
)
from .models import IndexManifest, IndexProduct, IndexSettings, VectorSettings

INDEX_VERSION: Final = "v1"
BAD_INDEX_VERSION: Final = "bad-index-version"


@dataclass(frozen=True, slots=True)
class IndexBuildRequest:
    """Candidate materialization and exact version tuple to fit."""

    materialization_id: int
    normalization_version: str
    tokenizer_version: str
    index_version: str
    products: tuple[IndexProduct, ...]


@dataclass(frozen=True, slots=True)
class IndexBundle:
    """Eight data members plus the excluded noncircular manifest."""

    members: tuple[tuple[str, bytes], ...]
    manifest: bytes
    artifact_sha256: str
    manifest_sha256: str

    @property
    def member_names(self) -> tuple[str, ...]:
        """Return the byte-contract member order."""
        return tuple(name for name, _value in self.members)

    def member(self, name: str) -> bytes:
        """Return one exact member by its fixed ASCII name."""
        return dict(self.members)[name]


@dataclass(frozen=True, slots=True)
class _VectorArtifact:
    vocabulary: bytes
    idf: bytes
    matrix: bytes
    settings: VectorSettings


def build_index(request: IndexBuildRequest) -> IndexBundle:
    """Fit word and character TF-IDF over the global active corpus."""
    if request.index_version != INDEX_VERSION:
        raise IndexFormatError(BAD_INDEX_VERSION)
    products = tuple(
        sorted(
            (item for item in request.products if item.active),
            key=lambda item: item.product_id.encode("utf-8"),
        )
    )
    normalized = tuple(normalize_text(item.option_text) for item in products)
    word_docs = tuple(item.tokens for item in normalized)
    char_docs = tuple(item.derived for item in normalized)
    word = _build_word(word_docs)
    char = _build_char(char_docs)
    rows_bytes = canonical_json(
        [
            {"product_id": product.product_id, "row": row}
            for row, product in enumerate(products)
        ]
    ).encode("utf-8")
    settings = IndexSettings(
        materialization_id=request.materialization_id,
        normalization_version=request.normalization_version,
        tokenizer_version=request.tokenizer_version,
        index_version=request.index_version,
        word=word.settings,
        char=char.settings,
    )
    settings_bytes = _model_jcs(settings)
    member_map = {
        "char-idf.f64le": char.idf,
        "char-matrix.csr1": char.matrix,
        "char-vocabulary.json": char.vocabulary,
        "product-rows.json": rows_bytes,
        "settings.json": settings_bytes,
        "word-idf.f64le": word.idf,
        "word-matrix.csr1": word.matrix,
        "word-vocabulary.json": word.vocabulary,
    }
    members = tuple((name, member_map[name]) for name in EXACT_MEMBER_NAMES)
    artifact_sha = artifact_sha256(members)
    manifest = IndexManifest(
        materialization_id=request.materialization_id,
        normalization_version=request.normalization_version,
        tokenizer_version=request.tokenizer_version,
        index_version=request.index_version,
        artifact_sha256=artifact_sha,
        member_sha256={
            name: hashlib.sha256(value).hexdigest() for name, value in members
        },
    )
    manifest_bytes = _model_jcs(manifest)
    bundle = IndexBundle(
        members,
        manifest_bytes,
        artifact_sha,
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    _ = validate_bundle(bundle.members, bundle.manifest)
    return bundle


def _build_word(documents: tuple[tuple[str, ...], ...]) -> _VectorArtifact:
    probe = word_vectorizer(None)
    analyzer = probe.build_analyzer()
    features = _feature_order(
        tuple(feature for document in documents for feature in analyzer(document))
    )
    return _fit(documents, features, "word", "identity", (1, 2))


def _build_char(documents: tuple[str, ...]) -> _VectorArtifact:
    probe = char_vectorizer(None)
    analyzer = probe.build_analyzer()
    features = _feature_order(
        tuple(feature for document in documents for feature in analyzer(document))
    )
    return _fit(documents, features, "char_wb", None, (3, 5))


def _fit(
    documents: tuple[tuple[str, ...], ...] | tuple[str, ...],
    features: tuple[str, ...],
    analyzer_name: str,
    tokenizer_name: str | None,
    ngram_range: tuple[int, int],
) -> _VectorArtifact:
    vocabulary = {feature: index for index, feature in enumerate(features)}
    vocabulary_json: dict[str, JsonValue] = dict(vocabulary)
    vocabulary_bytes = canonical_json(vocabulary_json).encode("utf-8")
    if not features:
        rows = len(documents)
        matrix_bytes = serialize_csr1(
            rows,
            0,
            tuple(0 for _ in range(rows + 1)),
            (),
            (),
        )
        idf_bytes = b""
    else:
        vectorizer = (
            word_vectorizer(vocabulary)
            if analyzer_name == "word"
            else char_vectorizer(vocabulary)
        )
        matrix = csr_matrix(vectorizer.fit_transform(documents), dtype=np.float64)
        matrix.sum_duplicates()
        matrix.eliminate_zeros()
        matrix.sort_indices()
        matrix_bytes = serialize_csr1(
            matrix.shape[0],
            matrix.shape[1],
            tuple(int(value) for value in matrix.indptr),
            tuple(int(value) for value in matrix.indices),
            tuple(float(value) for value in matrix.data),
        )
        idf_bytes = np.asarray(vectorizer.idf_, dtype="<f8").tobytes(order="C")
    settings = VectorSettings(
        analyzer=analyzer_name,
        tokenizer=tokenizer_name,
        preprocessor=None,
        token_pattern=None,
        ngram_range=ngram_range,
        lowercase=False,
        norm="l2",
        use_idf=True,
        smooth_idf=True,
        sublinear_tf=False,
        binary=False,
        dtype="float64",
        features=features,
        vocabulary_sha256=hashlib.sha256(vocabulary_bytes).hexdigest(),
        idf_sha256=hashlib.sha256(idf_bytes).hexdigest(),
    )
    return _VectorArtifact(vocabulary_bytes, idf_bytes, matrix_bytes, settings)


def _identity(tokens: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(tokens)


def word_vectorizer(vocabulary: dict[str, int] | None) -> TfidfVectorizer:
    """Create the exact v1 pretokenized word vectorizer."""
    return TfidfVectorizer(
        analyzer="word",
        tokenizer=_identity,
        preprocessor=None,
        token_pattern=None,
        ngram_range=(1, 2),
        lowercase=False,
        norm="l2",
        use_idf=True,
        smooth_idf=True,
        sublinear_tf=False,
        binary=False,
        dtype=np.float64,
        vocabulary=vocabulary,
    )


def char_vectorizer(vocabulary: dict[str, int] | None) -> TfidfVectorizer:
    """Create the exact v1 raw normalized character vectorizer."""
    return TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        lowercase=False,
        norm="l2",
        use_idf=True,
        smooth_idf=True,
        sublinear_tf=False,
        binary=False,
        dtype=np.float64,
        vocabulary=vocabulary,
    )


def _feature_order(features: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(frozenset(features), key=lambda value: value.encode("utf-8")))


def _model_jcs(model: IndexSettings | IndexManifest) -> bytes:
    return canonical_json(model.model_dump(mode="json")).encode("utf-8")
