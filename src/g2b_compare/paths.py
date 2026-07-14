"""Immutable source-artifact paths and hash inventory validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .errors import (
    SourceArtifactError,
    SourceBaselineError,
    SourceCountError,
)

EXPECTED_SOURCE_COUNT: Final = 4
SHA256_HEX_LENGTH: Final = 64
SOURCE_HASH_BASELINE: Final = Path("docs/source-artifacts.sha256")
SOURCE_ARTIFACTS: Final = (
    Path(
        "docs/reference/조달청_OpenAPI참고자료_나라장터_종합쇼핑몰품목정보서비스_1.3.docx"
    ),
    Path("dataset")
    / Path("250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx"),
    Path("dataset/순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx"),
    Path("dataset")
    / Path(
        "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx"
    ),
)


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """Four source files proven against the immutable baseline."""

    paths: tuple[Path, ...]

    @property
    def count(self) -> int:
        """Return the verified artifact count."""
        return len(self.paths)


def validate_source_inventory(
    root: Path,
    source_paths: tuple[Path, ...] = SOURCE_ARTIFACTS,
    baseline_path: Path = SOURCE_HASH_BASELINE,
) -> SourceInventory:
    """Validate exact source presence, count, and SHA-256 declarations."""
    if len(source_paths) != EXPECTED_SOURCE_COUNT:
        raise SourceCountError(actual=len(source_paths))

    resolved_paths = tuple(root / relative for relative in source_paths)
    for path in resolved_paths:
        if not path.is_file():
            raise SourceArtifactError(path=path)

    baseline = root / baseline_path
    if not baseline.is_file():
        raise SourceBaselineError(detail=f"missing: {baseline}")

    declared = _parse_baseline(baseline)
    if len(declared) != EXPECTED_SOURCE_COUNT:
        raise SourceBaselineError(
            detail=f"expected 4 hashes, found {len(declared)}",
        )

    for relative, path in zip(source_paths, resolved_paths, strict=True):
        expected = declared.get(relative.as_posix())
        if expected is None:
            raise SourceBaselineError(detail=f"entry missing: {relative.as_posix()}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SourceBaselineError(detail=f"hash mismatch: {relative.as_posix()}")

    return SourceInventory(paths=resolved_paths)


def _parse_baseline(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != SHA256_HEX_LENGTH or not relative:
            raise SourceBaselineError(detail=f"malformed entry: {line}")
        entries[relative] = digest
    return entries
