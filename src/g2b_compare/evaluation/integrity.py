"""Collect Todo15 security and immutable-source evidence from real storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.errors import (
    SourceArtifactError,
    SourceBaselineError,
    SourceCountError,
)
from g2b_compare.observability.secrets import SecretLeak, verify_secrets
from g2b_compare.paths import validate_source_inventory

from .contracts import IntegrityContractFacts

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class IntegrityScanPlan:
    """Fixed repository, runtime, and immutable-source scan boundaries."""

    repository_root: Path
    runtime_root: Path
    source_root: Path
    source_paths: tuple[Path, ...]
    baseline_path: Path
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class IntegrityEvidence:
    """Observed leak locations and immutable-source verification result."""

    secret_leaks: tuple[SecretLeak, ...]
    source_count: int
    source_hashes_match: bool

    @property
    def facts(self) -> IntegrityContractFacts:
        """Convert observations into the aggregate Todo15 contract facts."""
        return IntegrityContractFacts(
            runtime_secret_matches=len(self.secret_leaks),
            source_hashes_match=self.source_hashes_match,
        )


def scan_integrity(plan: IntegrityScanPlan) -> IntegrityEvidence:
    """Execute the production all-storage scanner and source hash verifier."""
    leaks = verify_secrets(
        plan.repository_root,
        secret=plan.secret,
        runtime_root=plan.runtime_root,
        all_storage=True,
    )
    try:
        inventory = validate_source_inventory(
            plan.source_root,
            plan.source_paths,
            plan.baseline_path,
        )
    except (SourceArtifactError, SourceBaselineError, SourceCountError):
        source_count = 0
        hashes_match = False
    else:
        source_count = inventory.count
        hashes_match = True
    return IntegrityEvidence(leaks, source_count, hashes_match)
