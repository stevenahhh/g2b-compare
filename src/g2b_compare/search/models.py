"""Define trusted search artifact and candidate value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True, slots=True)
class IndexProduct:
    """One Todo 9 candidate projected into exact membership and ranking text."""

    product_id: str
    category_key: tuple[str, str]
    product_name_raw: str
    product_name_key: str
    option_text: str
    active: bool


class ProductRow(BaseModel):
    """Canonical product-to-CSR-row mapping member."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    product_id: str
    row: int


class VectorSettings(BaseModel):
    """Serialized v1 analyzer settings and deterministic feature order."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    analyzer: str
    tokenizer: str | None
    preprocessor: None
    token_pattern: None
    ngram_range: tuple[int, int]
    lowercase: bool
    norm: str
    use_idf: bool
    smooth_idf: bool
    sublinear_tf: bool
    binary: bool
    dtype: str
    features: tuple[str, ...]
    vocabulary_sha256: str
    idf_sha256: str


class IndexSettings(BaseModel):
    """Version and analyzer contract stored inside the artifact."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    materialization_id: int
    normalization_version: str
    tokenizer_version: str
    index_version: str
    word: VectorSettings
    char: VectorSettings


class IndexManifest(BaseModel):
    """Noncircular manifest covering exactly the eight framed members."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    materialization_id: int
    normalization_version: str
    tokenizer_version: str
    index_version: str
    artifact_sha256: str
    member_sha256: dict[str, str]
