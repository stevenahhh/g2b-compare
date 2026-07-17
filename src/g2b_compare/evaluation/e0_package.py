"""Canonical manifest serialization and atomic E0 package publication."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from g2b_compare.db.hashes import JsonValue, canonical_json, sha256_text

from .e0_models import E0ExportBlocked, FrozenE0Release
from .e0_parser import PARSER_STRATA, detector_sha256, domain_units_sha256


@dataclass(frozen=True, slots=True)
class ManifestSelection:
    """Group, stratum, and split receipts for one seed."""

    seed: str
    splits: dict[tuple[str, str], str]
    strata: dict[str, int]
    split_counts: dict[str, int]
    parser_positive_spans: int
    parser_semantic_results: int
    parser_negative_rows: int


def build_manifest(
    release: FrozenE0Release,
    payloads: dict[str, bytes],
    selection: ManifestSelection,
) -> dict[str, JsonValue]:
    """Build the byte-stable E0 component and selection receipt."""
    identity = release.identity
    split_map: dict[str, JsonValue] = {
        _category_json(group): split
        for group, split in sorted(selection.splits.items())
    }
    file_schemas = {
        "assessor-a.template.jsonl": "assessor-template-v1",
        "assessor-b.template.jsonl": "assessor-template-v1",
        "parser.template.jsonl": "parser-template-v1",
        "pool.jsonl": "e0-pool-v1",
    }
    files: dict[str, JsonValue] = {
        name: {
            "record_count": len(payload.splitlines()),
            "schema_version": file_schemas[name],
            "sha256": sha256_bytes(payload),
            "size": len(payload),
        }
        for name, payload in sorted(payloads.items())
    }
    parser_strata: dict[str, JsonValue] = dict.fromkeys(PARSER_STRATA, 50)
    release_values: dict[str, JsonValue] = {
        "bundle_id": identity.bundle_id,
        "char_idf_sha": identity.char_idf_sha,
        "index_artifact_sha": identity.index_artifact_sha,
        "index_manifest_sha": identity.index_manifest_sha,
        "materialization_id": identity.materialization_id,
        "materialization_sha": identity.materialization_sha,
        "ranking_version": identity.ranking_version,
        "relation_snapshot_sha": identity.relation_snapshot_sha,
        "release_bundle_sha": identity.release_bundle_sha,
        "word_idf_sha": identity.word_idf_sha,
    }
    split_counts: dict[str, JsonValue] = dict(selection.split_counts)
    strata: dict[str, JsonValue] = dict(selection.strata)
    manifest: dict[str, JsonValue] = {
        "completed_at_utc": identity.created_at_utc,
        "counts": {
            "anchors": 200,
            "pairs": 2000,
            "parser_negative_rows": selection.parser_negative_rows,
            "parser_positive_spans": selection.parser_positive_spans,
            "parser_rows": 500,
            "parser_semantic_results": selection.parser_semantic_results,
        },
        "detector_regex_sha256": detector_sha256(),
        "domain_unit_set_sha256": domain_units_sha256(),
        "export_id": sha256_text(f"{selection.seed}|{identity.release_bundle_sha}"),
        "files": files,
        "label_scale": [0, 1, 2, 3],
        "group_counts": {
            group: {
                "anchor_count": 20,
                "pair_count": 200,
                "split": split,
            }
            for group, split in split_map.items()
        },
        "parser_strata": parser_strata,
        "release": release_values,
        "schema_version": "e0-export-v1",
        "seed": selection.seed,
        "started_at_utc": identity.created_at_utc,
        "split_counts": split_counts,
        "split_map": split_map,
        "split_map_sha256": sha256_text(canonical_json(split_map)),
        "strata": strata,
        "parser_template_sha256": sha256_bytes(payloads["parser.template.jsonl"]),
    }
    return manifest


def serialize_jsonl(rows: tuple[dict[str, JsonValue], ...]) -> bytes:
    """Serialize canonical UTF-8 JSON lines with one final LF."""
    return ("\n".join(canonical_json(row) for row in rows) + "\n").encode("utf-8")


def serialize_manifest(manifest: dict[str, JsonValue]) -> bytes:
    """Serialize one canonical manifest with one final LF."""
    return (canonical_json(manifest) + "\n").encode("utf-8")


def publish_package(output: Path, payloads: dict[str, bytes]) -> None:
    """Publish a new immutable directory with one atomic rename."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        detail = f"immutable output already exists: {output}"
        raise E0ExportBlocked(detail)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for name, payload in payloads.items():
            _ = (temporary / name).write_bytes(payload)
        _ = temporary.replace(output)
    except OSError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def sha256_bytes(payload: bytes) -> str:
    """Return one lowercase SHA-256 byte digest."""
    return hashlib.sha256(payload).hexdigest()


def _category_json(group: tuple[str, str]) -> str:
    return canonical_json({"category_no": group[0], "detail_category_no": group[1]})
