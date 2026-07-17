"""Typed records shared by comparator calculation and cache decoding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override

if TYPE_CHECKING:
    from decimal import Decimal

    from g2b_compare.ranking.explain import ScoreBreakdown
    from g2b_compare.ranking.topk import RankableProduct

CACHE_CORRUPT: Final = "corrupt_cache"
type ComparatorStatus = Literal[
    "ok",
    "no_comparison_evidence",
    "insufficient_candidates",
]


@dataclass(frozen=True, slots=True)
class ObservedOptionRole:
    """One delivery event preserved without inferring a parent relation."""

    source_snapshot_id: int
    source_row_key: str
    delivery_request_key: str
    item_sequence: str
    change_sequence: str
    role_raw: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class CuratedRelation:
    """One relation pinned to the release's curated snapshot."""

    relation_id: str
    parent_id: str
    child_id: str
    source_type: str
    source_sha: str
    sheet_name: str
    row_no: int


@dataclass(frozen=True, slots=True)
class ProductRecord:
    """Search projection plus event and curated provenance."""

    rankable: RankableProduct
    product_name_raw: str
    data_as_of: str
    attribute_coverage: str
    observed_option_roles: tuple[ObservedOptionRole, ...] = ()
    curated_relations: tuple[CuratedRelation, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchedQuantity:
    """One structured anchor-to-candidate quantity match."""

    anchor_start: int
    candidate_start: int
    attribute_key: str
    dimension: str
    value_similarity: Decimal


@dataclass(frozen=True, slots=True)
class ScoredRecord:
    """One exact-pool product scored from the virtual query anchor."""

    record: ProductRecord
    scores: ScoreBreakdown
    matched_quantities: tuple[MatchedQuantity, ...]
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparatorScores:
    """Six persisted Ranking-v1 values exposed by a comparator slot."""

    lexical: Decimal | None
    fuzzy: Decimal | None
    structured: Decimal | None
    price: Decimal | None
    score: Decimal | None
    coverage: Decimal | None


@dataclass(frozen=True, slots=True)
class ComparatorView:
    """One stable cache-compatible comparator response slot."""

    anchor_id: str
    rank: int
    status: ComparatorStatus
    candidate: ProductRecord | None
    scores: ComparatorScores | None
    matched_quantities: tuple[MatchedQuantity, ...]
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparatorCacheError(Exception):
    """Reject incomplete, stale, or internally inconsistent cached slots."""

    detail: str = CACHE_CORRUPT

    @override
    def __str__(self) -> str:
        return self.detail
