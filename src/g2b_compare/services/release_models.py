"""Typed public contracts for release coordination and request pinning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, final, override

if TYPE_CHECKING:
    from g2b_compare.ranking.cache import CachePayload


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """Exact component IDs and ranking version for one unique bundle."""

    materialization_id: int
    index_version_id: int
    relation_snapshot_id: int
    ranking_version: str
    slot_policy_version: str = "v2"


@dataclass(frozen=True, slots=True)
class ReleasePin:
    """One request-scoped immutable ready release graph identity."""

    bundle_id: int
    ready_attempt_no: int
    materialization_id: int
    index_version_id: int
    relation_snapshot_id: int
    ranking_version: str
    normalization_version: str
    materialization_policy_version: str
    materialization_source_sha: str
    index_artifact_sha: str
    index_manifest_sha: str
    relation_source_manifest_sha: str
    relation_content_sha: str
    data_as_of: str
    slot_policy_version: str = "v2"


class ReleaseDisposition(StrEnum):
    """Coordinator outcomes that do not hide an error."""

    READY = "ready"
    READY_NOOP = "ready-noop"
    BUILDING_NOOP = "building-noop"


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    """One completed or deliberately unchanged coordinator invocation."""

    disposition: ReleaseDisposition
    bundle_id: int
    attempt_no: int
    pin: ReleasePin | None


class ComparatorCacheBuilder(Protocol):
    """Build the exact ordered slot payloads for one active anchor."""

    def slots_for(self, anchor_id: str) -> tuple[CachePayload, ...]:
        """Return exactly three payloads ordered by slot."""
        ...


@final
class ReleaseContractError(Exception):
    """A release candidate or persisted ready bundle is inconsistent."""

    code: str

    def __init__(self, code: str) -> None:
        """Initialize one stable machine-readable release error."""
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code
