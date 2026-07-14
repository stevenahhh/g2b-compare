"""Strict validation for immutable, externally authored E0 packages."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError

from g2b_compare.errors import (
    E0CountError,
    E0HashError,
    E0MissingFileError,
    E0SchemaError,
    E0StratumError,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SAFE_PATH_ERROR_CODE: Final = "safe_relative_path"
SAFE_PATH_ERROR_MESSAGE: Final = "declared file path must be a safe relative path"


class E0Record(BaseModel):
    """One externally authored binary relevance assessment."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    record_id: str = Field(min_length=1)
    stratum: str = Field(min_length=1)
    label: Literal[0, 1]


class E0FileDeclaration(BaseModel):
    """Expected hash, count, and strata for one records file."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    path: Path
    sha256: Sha256
    record_count: PositiveInt
    strata: dict[str, PositiveInt]

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: Path) -> Path:
        """Prevent declarations from escaping the assessment package."""
        if value.is_absolute() or ".." in value.parts:
            raise PydanticCustomError(
                SAFE_PATH_ERROR_CODE,
                SAFE_PATH_ERROR_MESSAGE,
            )
        return value


class E0Manifest(BaseModel):
    """Versioned trust boundary for an E0 package manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["e0-v1"]
    total_count: PositiveInt
    strata: dict[str, PositiveInt]
    files: tuple[E0FileDeclaration, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class E0ValidationReport:
    """Counts proven by successful non-mutating validation."""

    total_count: int
    file_count: int
    strata: dict[str, int]


def validate_e0_package(manifest_path: Path) -> E0ValidationReport:
    """Validate schema, file presence, hashes, counts, and strata."""
    if not manifest_path.is_file():
        raise E0MissingFileError(path=manifest_path)

    try:
        manifest = E0Manifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError as error:
        raise E0SchemaError(path=manifest_path, detail=str(error)) from None

    total_count = 0
    total_strata: Counter[str] = Counter()
    for declaration in manifest.files:
        records_path = manifest_path.parent / declaration.path
        if not records_path.is_file():
            raise E0MissingFileError(path=records_path)

        payload = records_path.read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != declaration.sha256:
            raise E0HashError(
                path=records_path,
                expected=declaration.sha256,
                actual=actual_hash,
            )

        records = _parse_records(records_path, payload)
        actual_count = len(records)
        if actual_count != declaration.record_count:
            raise E0CountError(
                scope=declaration.path.as_posix(),
                expected=declaration.record_count,
                actual=actual_count,
            )

        actual_strata = dict(Counter(record.stratum for record in records))
        expected_strata = dict(declaration.strata)
        if actual_strata != expected_strata:
            raise E0StratumError(
                scope=declaration.path.as_posix(),
                expected=expected_strata,
                actual=actual_strata,
            )
        total_count += actual_count
        total_strata.update(actual_strata)

    if total_count != manifest.total_count:
        raise E0CountError(
            scope="manifest",
            expected=manifest.total_count,
            actual=total_count,
        )

    actual_total_strata = dict(total_strata)
    expected_total_strata = dict(manifest.strata)
    if actual_total_strata != expected_total_strata:
        raise E0StratumError(
            scope="manifest",
            expected=expected_total_strata,
            actual=actual_total_strata,
        )

    return E0ValidationReport(
        total_count=total_count,
        file_count=len(manifest.files),
        strata=actual_total_strata,
    )


def _parse_records(path: Path, payload: bytes) -> tuple[E0Record, ...]:
    records: list[E0Record] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        try:
            records.append(E0Record.model_validate_json(line))
        except ValidationError as error:
            detail = f"record {line_number}: {error}"
            raise E0SchemaError(path=path, detail=detail) from None
    return tuple(records)
