"""Bind index ownership and vector settings to actual member bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import IndexManifest, IndexSettings, VectorSettings


@dataclass(frozen=True, slots=True)
class IndexIdentity:
    """Exact materialization and algorithm version ownership tuple."""

    materialization_id: int
    normalization_version: str
    tokenizer_version: str
    index_version: str


def derive_integrity_identity(
    manifest: IndexManifest,
    settings: IndexSettings,
    members: dict[str, bytes],
    word_vocab: dict[str, int],
    char_vocab: dict[str, int],
) -> IndexIdentity | None:
    """Return identity only when settings derive from the actual eight members."""
    manifest_identity = IndexIdentity(
        manifest.materialization_id,
        manifest.normalization_version,
        manifest.tokenizer_version,
        manifest.index_version,
    )
    settings_identity = IndexIdentity(
        settings.materialization_id,
        settings.normalization_version,
        settings.tokenizer_version,
        settings.index_version,
    )
    if manifest_identity != settings_identity:
        return None
    if not _vector_matches(
        settings.word,
        word_vocab,
        members["word-vocabulary.json"],
        members["word-idf.f64le"],
        expected=("word", "identity", (1, 2)),
    ):
        return None
    if not _vector_matches(
        settings.char,
        char_vocab,
        members["char-vocabulary.json"],
        members["char-idf.f64le"],
        expected=("char_wb", None, (3, 5)),
    ):
        return None
    return manifest_identity


def _vector_matches(
    settings: VectorSettings,
    vocabulary: dict[str, int],
    vocabulary_bytes: bytes,
    idf_bytes: bytes,
    *,
    expected: tuple[str, str | None, tuple[int, int]],
) -> bool:
    features = tuple(
        feature
        for feature, _index in sorted(vocabulary.items(), key=lambda item: item[1])
    )
    fixed = (
        settings.analyzer,
        settings.tokenizer,
        settings.ngram_range,
        settings.preprocessor,
        settings.token_pattern,
        settings.lowercase,
        settings.norm,
        settings.use_idf,
        settings.smooth_idf,
        settings.sublinear_tf,
        settings.binary,
        settings.dtype,
    )
    expected_fixed = (
        *expected,
        None,
        None,
        False,
        "l2",
        True,
        True,
        False,
        False,
        "float64",
    )
    return (
        fixed == expected_fixed
        and settings.features == features
        and settings.vocabulary_sha256 == hashlib.sha256(vocabulary_bytes).hexdigest()
        and settings.idf_sha256 == hashlib.sha256(idf_bytes).hexdigest()
    )
