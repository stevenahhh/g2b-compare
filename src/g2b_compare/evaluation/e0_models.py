"""Typed frozen-release and E0 export value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, final, override

type ParserFieldKind = Literal["raw_value", "spec_name", "detail", "characteristic"]
type E0Split = Literal["train", "validation", "test"]
type Lane = Literal["lexical", "structured", "price", "hash", "backfill"]


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """Immutable component identities pinned by one ready release bundle."""

    bundle_id: int
    release_bundle_sha: str
    materialization_id: int
    materialization_sha: str
    index_artifact_sha: str
    index_manifest_sha: str
    word_idf_sha: str
    char_idf_sha: str
    relation_snapshot_sha: str
    ranking_version: str
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class E0Product:
    """Frozen product projection needed by the strict selection algorithm."""

    product_id: str
    category_no: str
    detail_category_no: str
    product_name_key: str
    option_text: str
    active: bool
    attribute_count: int
    price_won: int | None
    price_unit: str | None

    @property
    def category_tuple(self) -> tuple[str, str]:
        """Return the exact category group key."""
        return self.category_no, self.detail_category_no


@dataclass(frozen=True, slots=True)
class ParserSource:
    """One source-provenance-preserving raw parser template candidate."""

    product_id: str
    field_kind: ParserFieldKind
    source_key: str
    ordinal: int
    text: str


@dataclass(frozen=True, slots=True)
class FrozenE0Release:
    """Complete read-only input captured inside one release transaction."""

    identity: ReleaseIdentity
    products: tuple[E0Product, ...]
    parser_sources: tuple[ParserSource, ...]


@dataclass(frozen=True, slots=True)
class E0ExportReport:
    """Machine-readable receipt for one atomic immutable export."""

    manifest_sha256: str
    anchor_count: int
    pair_count: int
    parser_row_count: int
    split_counts: dict[str, int]


@final
class E0ExportBlockedError(Exception):
    """Expected strict-gate refusal carrying a stable reason."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one stable refusal reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


E0ExportBlocked = E0ExportBlockedError
