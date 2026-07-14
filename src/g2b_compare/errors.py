"""Typed errors emitted by configuration and evaluation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from pathlib import Path


class G2BCompareError(Exception):
    """Base class for expected application boundary errors."""


@dataclass(frozen=True, slots=True)
class SourceArtifactError(G2BCompareError):
    """A declared source artifact is absent."""

    path: Path

    @override
    def __str__(self) -> str:
        return f"source artifact is missing: {self.path}"


@dataclass(frozen=True, slots=True)
class SourceBaselineError(G2BCompareError):
    """The source hash baseline is absent, malformed, or stale."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"hash baseline validation failed: {self.detail}"


@dataclass(frozen=True, slots=True)
class SourceCountError(G2BCompareError):
    """The immutable source inventory does not contain four files."""

    actual: int

    @override
    def __str__(self) -> str:
        return f"expected 4 source artifacts, found {self.actual}"


@dataclass(frozen=True, slots=True)
class E0MissingFileError(G2BCompareError):
    """An E0 manifest or declared assessment file is absent."""

    path: Path

    @override
    def __str__(self) -> str:
        return f"E0 declared file is missing: {self.path}"


@dataclass(frozen=True, slots=True)
class E0SchemaError(G2BCompareError):
    """An E0 manifest or record violates the versioned schema."""

    path: Path
    detail: str

    @override
    def __str__(self) -> str:
        return f"E0 schema validation failed for {self.path}: {self.detail}"


@dataclass(frozen=True, slots=True)
class E0CountError(G2BCompareError):
    """Observed E0 record counts differ from declared counts."""

    scope: str
    expected: int
    actual: int

    @override
    def __str__(self) -> str:
        return (
            f"E0 count mismatch for {self.scope}: "
            f"expected {self.expected}, found {self.actual}"
        )


@dataclass(frozen=True, slots=True)
class E0StratumError(G2BCompareError):
    """Observed E0 strata differ from declared strata."""

    scope: str
    expected: dict[str, int]
    actual: dict[str, int]

    @override
    def __str__(self) -> str:
        return (
            f"E0 stratum mismatch for {self.scope}: "
            f"expected {self.expected}, found {self.actual}"
        )


@dataclass(frozen=True, slots=True)
class E0HashError(G2BCompareError):
    """An E0 file differs from its declared content hash."""

    path: Path
    expected: str
    actual: str

    @override
    def __str__(self) -> str:
        return (
            f"E0 hash mismatch for {self.path}: "
            f"expected {self.expected}, found {self.actual}"
        )
