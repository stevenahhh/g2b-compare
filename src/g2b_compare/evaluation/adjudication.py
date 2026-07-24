"""External strict-evaluation prerequisite boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from g2b_compare.errors import G2BCompareError

from .e0_schema import validate_e0_package
from .e0_strict_validation import StrictValidationFacts

if TYPE_CHECKING:
    from pathlib import Path

MISSING_GOLD: Final = "missing-gold-manifest"
MISSING_SOURCE: Final = "missing-source-export"
INVALID_EXTERNAL: Final = "invalid-external-evaluation"


@dataclass(frozen=True, slots=True)
class ExternalEvaluationBlockedError(Exception):
    """Prevent a release from substituting generated labels for external work."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def require_external_evaluation(
    manifest_path: Path,
    source_export_path: Path,
) -> StrictValidationFacts:
    """Validate a supplied package without creating or modifying any labels."""
    if not manifest_path.is_file():
        raise ExternalEvaluationBlockedError(MISSING_GOLD)
    if not source_export_path.is_file():
        raise ExternalEvaluationBlockedError(MISSING_SOURCE)
    try:
        result = validate_e0_package(
            manifest_path,
            strict=True,
            source_export=source_export_path,
        )
    except (G2BCompareError, OSError):
        raise ExternalEvaluationBlockedError(INVALID_EXTERNAL) from None
    if not isinstance(result, StrictValidationFacts):
        raise ExternalEvaluationBlockedError(INVALID_EXTERNAL)
    return result
