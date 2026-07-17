"""Typed strict-gold manifest and row schemas."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Split = Literal["train", "validation", "test"]
Label = Literal[0, 1, 2, 3]


class StrictFile(BaseModel):
    """One immutable file receipt declared by a strict manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    record_count: int = Field(ge=0)
    schema_version: str
    sha256: Sha256
    size: int = Field(ge=0)


class StrictCounts(BaseModel):
    """Fixed E0 population and parser target counts."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    adjudications: int = Field(ge=0)
    anchors: Literal[200]
    pairs: Literal[2000]
    parser_negative_rows: Literal[50]
    parser_positive_spans: Literal[500]
    parser_rows: Literal[500]
    parser_semantic_results: Literal[600]


class SourceExportIdentity(BaseModel):
    """Exact frozen-export identities claimed by strict gold."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    bundle_id: int = Field(ge=1)
    char_idf_sha: Sha256
    export_id: Sha256
    index_artifact_sha: Sha256
    index_manifest_sha: Sha256
    manifest_sha256: Sha256
    materialization_id: int = Field(ge=1)
    materialization_sha: Sha256
    parser_template_sha256: Sha256
    ranking_version: str = Field(min_length=1)
    relation_snapshot_sha: Sha256
    release_bundle_sha: Sha256
    word_idf_sha: Sha256


class StrictManifest(BaseModel):
    """Trust boundary for externally labeled E0 data."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    adjudicator_id: str = Field(min_length=1)
    assessor_ids: tuple[str, str]
    completed_at_utc: str
    counts: StrictCounts
    files: dict[str, StrictFile]
    label_scale: tuple[Literal[0, 1, 2, 3], ...]
    schema_version: Literal["e0-strict-v1"]
    seed: str
    source_export: SourceExportIdentity
    split_counts: dict[str, int]
    started_at_utc: str


class AssessorRow(BaseModel):
    """One blinded relevance judgment from an assessor."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    assessor_id: str = Field(min_length=1)
    anchor_id: str
    candidate_id: str
    blinded_ordinal: int = Field(ge=1, le=10)
    label_0_3: Label
    reason: str
    split: Split


class AdjudicationRow(BaseModel):
    """One independent resolution of an assessor disagreement."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    adjudicator_id: str = Field(min_length=1)
    anchor_id: str
    candidate_id: str
    label_a: Label
    label_b: Label
    final_label: Label
    reason: str
    split: Split


class GoldRow(BaseModel):
    """One finalized relevance judgment."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    anchor_id: str
    candidate_id: str
    final_label: Label
    reason: str
    split: Split


class ParserSemantic(BaseModel):
    """One normalized semantic value extracted from a parser span."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    attribute_key: str
    canonical_unit: str
    dimension: str
    lower: str | None
    relation: Literal["eq", "lt", "le", "gt", "ge", "range"]
    upper: str | None
    value_decimal: str


class ParserSpan(BaseModel):
    """One byte-addressed source span and its semantics."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    end_byte: int = Field(gt=0)
    raw: str
    semantics: tuple[ParserSemantic, ...] = Field(min_length=1, max_length=3)
    start_byte: int = Field(ge=0)


class ParserGoldRow(BaseModel):
    """One finalized parser-gold example."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    spans: tuple[ParserSpan, ...] = Field(max_length=2)
    split: Split
    stratum: str
    supported: bool
    text: str
