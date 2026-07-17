"""Typed schemas and constants for an unlabeled E0 export package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from g2b_compare.db.hashes import JsonValue

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Split = Literal["train", "validation", "test"]

ANCHOR_COUNT: Final = 200
PAIR_COUNT: Final = 2_000
CANDIDATE_COUNT: Final = 10
PARSER_ROW_COUNT: Final = 500
PARSER_SPAN_COUNT: Final = 500
PARSER_SEMANTIC_COUNT: Final = 600
PARSER_NEGATIVE_COUNT: Final = 50


class ExportFile(BaseModel):
    """One immutable file receipt declared by the export manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    record_count: int = Field(ge=0)
    schema_version: str
    sha256: Sha256
    size: int = Field(ge=0)


class ExportCounts(BaseModel):
    """Fixed E0 population and parser target counts."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    anchors: Literal[200]
    pairs: Literal[2000]
    parser_negative_rows: Literal[50]
    parser_positive_spans: Literal[500]
    parser_rows: Literal[500]
    parser_semantic_results: Literal[600]


class GroupCount(BaseModel):
    """Expected counts and split for one category group."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    anchor_count: Literal[20]
    pair_count: Literal[200]
    split: Split


class ExportReleaseIdentity(BaseModel):
    """Frozen release identities embedded by every exported pool row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    bundle_id: int = Field(ge=1)
    char_idf_sha: Sha256
    index_artifact_sha: Sha256
    index_manifest_sha: Sha256
    materialization_id: int = Field(ge=1)
    materialization_sha: Sha256
    ranking_version: str = Field(min_length=1)
    relation_snapshot_sha: Sha256
    release_bundle_sha: Sha256
    word_idf_sha: Sha256


class ExportManifest(BaseModel):
    """Trust boundary for an immutable unlabeled export."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["e0-export-v1"]
    started_at_utc: str
    completed_at_utc: str
    counts: ExportCounts
    detector_regex_sha256: Sha256
    domain_unit_set_sha256: Sha256
    export_id: Sha256
    files: dict[str, ExportFile]
    group_counts: dict[str, GroupCount]
    label_scale: tuple[Literal[0, 1, 2, 3], ...]
    parser_strata: dict[str, int]
    parser_template_sha256: Sha256
    release: ExportReleaseIdentity
    seed: str
    split_counts: dict[str, int]
    split_map: dict[str, Split]
    split_map_sha256: Sha256
    strata: dict[str, int]


class CategoryTuple(BaseModel):
    """Canonical category-group identity for one pool row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    category_no: str
    detail_category_no: str


class PoolRow(BaseModel):
    """One candidate comparison in the deterministic export pool."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    anchor_id: str
    anchor_stratum: str
    candidate_id: str
    category_tuple: CategoryTuple
    exact_name_key: str
    lane: Literal["lexical", "structured", "price", "hash", "backfill"]
    lane_value: str
    ranking_version: str
    source_index_sha: Sha256
    source_materialization_sha: Sha256
    source_release_bundle_sha: Sha256
    split: Split


class AssessorTemplateRow(BaseModel):
    """One blinded, unlabeled assessor assignment."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    anchor_id: str
    assessor_slot: Literal["a", "b"]
    blinded_ordinal: int = Field(ge=1, le=10)
    candidate_id: str


class ParserTemplateRow(BaseModel):
    """One unlabeled parser assignment with declared aggregate targets."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    expected_semantic_result_count: int = Field(ge=0, le=3)
    expected_span_count: int = Field(ge=0, le=2)
    row_id: str
    source: dict[str, JsonValue]
    spans: tuple[JsonValue, ...]
    split: Split
    stratum: str
    text: str


@dataclass(frozen=True, slots=True)
class ExportValidationFacts:
    """Facts proven by successful unlabeled export validation."""

    total_count: int
    file_count: int
    strata: dict[str, int]


EXPECTED_FILES: Final = {
    "assessor-a.template.jsonl": ("assessor-template-v1", PAIR_COUNT),
    "assessor-b.template.jsonl": ("assessor-template-v1", PAIR_COUNT),
    "parser.template.jsonl": ("parser-template-v1", PARSER_ROW_COUNT),
    "pool.jsonl": ("e0-pool-v1", PAIR_COUNT),
}
_ = ExportManifest.model_rebuild(_types_namespace={"JsonValue": JsonValue})
_ = ParserTemplateRow.model_rebuild(_types_namespace={"JsonValue": JsonValue})
POOL_ADAPTER = TypeAdapter(PoolRow)
ASSESSOR_ADAPTER = TypeAdapter(AssessorTemplateRow)
PARSER_ADAPTER = TypeAdapter(ParserTemplateRow)
