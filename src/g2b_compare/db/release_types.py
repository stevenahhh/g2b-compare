"""Typed values shared by release attempt and publication stores."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, final, override

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReleaseKey:
    """Unique database tuple for one release bundle."""

    materialization_id: int
    index_version_id: int
    relation_snapshot_id: int
    ranking_version: str
    slot_policy_version: str = "v2"


class BundleStatus(StrEnum):
    """Persisted release build states."""

    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BundleRecord:
    """Typed state for one claimed or replayed release tuple."""

    bundle_id: int
    status: BundleStatus
    attempt_no: int
    expected_rows: int
    written_rows: int
    cache_sha: str | None
    bundle_sha: str | None
    ready_attempt_no: int | None
    owned: bool


@dataclass(frozen=True, slots=True)
class ReadyValues:
    """Final cache cardinality, hashes, and transition time."""

    written: int
    cache_sha: str
    bundle_sha: str
    now: datetime


@final
class ReleaseStoreError(Exception):
    """A persisted release graph violates the coordinator contract."""

    code: str

    def __init__(self, code: str) -> None:
        """Initialize one stable machine-readable release error."""
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code


def key_values(key: ReleaseKey) -> tuple[int, int, int, str, str]:
    """Project one key into canonical SQL parameter order."""
    return (
        key.materialization_id,
        key.index_version_id,
        key.relation_snapshot_id,
        key.ranking_version,
        key.slot_policy_version,
    )
