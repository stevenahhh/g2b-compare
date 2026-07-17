"""Deterministic complete strict-gold package fixture."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue, canonical_json

if TYPE_CHECKING:
    from pathlib import Path

PARSER_STRATA = (
    "scalar",
    "decimal-comma",
    "arabic-man",
    "relation",
    "range",
    "dimension",
    "domain-unit",
    "si-case",
    "zero-negative-unsupported",
    "compound-mixed",
)
JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class _StrictFixtureContext:
    disagreements: set[tuple[str, str]]
    labels: dict[tuple[str, str], int]
    pool: dict[tuple[str, str], dict[str, JsonValue]]
    unrelated: bool


def write_strict_package(
    root: Path,
    source_manifest: Path,
    *,
    disagreement_count: int = 0,
    unrelated: bool = False,
) -> Path:
    root.mkdir()
    source_root = source_manifest.parent
    source = JSON_ADAPTER.validate_json(source_manifest.read_bytes())
    pool = _load_rows(source_root / "pool.jsonl")
    templates = {
        "a": _load_rows(source_root / "assessor-a.template.jsonl"),
        "b": _load_rows(source_root / "assessor-b.template.jsonl"),
    }
    parser_template = _load_rows(source_root / "parser.template.jsonl")
    pool_by_pair = {_pair(row): row for row in pool}
    ordered_pairs = sorted(pool_by_pair)
    disagreements = set(ordered_pairs[:disagreement_count])
    labels = {pair: index % 4 for index, pair in enumerate(ordered_pairs)}
    context = _StrictFixtureContext(disagreements, labels, pool_by_pair, unrelated)
    assessor_a = _assessor_rows(templates["a"], context, "a")
    assessor_b = _assessor_rows(templates["b"], context, "b")
    adjudication = _adjudication_rows(pool_by_pair, labels, disagreements, unrelated)
    gold = _gold_rows(pool, labels, disagreements, unrelated)
    parser = tuple(_parser_row(row) for row in parser_template)
    payloads = {
        "adjudication.jsonl": _jsonl(adjudication),
        "assessor-a.jsonl": _jsonl(tuple(assessor_a)),
        "assessor-b.jsonl": _jsonl(tuple(assessor_b)),
        "gold-v1.jsonl": _jsonl(tuple(gold)),
        "parser-gold-v1.jsonl": _jsonl(parser),
    }
    for name, payload in payloads.items():
        _ = (root / name).write_bytes(payload)
    files: dict[str, JsonValue] = {
        name: {
            "record_count": len(payload.splitlines()),
            "schema_version": name.removesuffix(".jsonl") + "-v1",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        for name, payload in payloads.items()
    }
    manifest: dict[str, JsonValue] = {
        "adjudicator_id": "gamma",
        "assessor_ids": ["alpha", "beta"],
        "completed_at_utc": "2026-07-14T00:00:00Z",
        "counts": {
            "adjudications": disagreement_count,
            "anchors": 200,
            "pairs": 2000,
            "parser_negative_rows": 50,
            "parser_positive_spans": 500,
            "parser_rows": 500,
            "parser_semantic_results": 600,
        },
        "files": files,
        "label_scale": [0, 1, 2, 3],
        "schema_version": "e0-strict-v1",
        "seed": source["seed"],
        "source_export": _source_identity(source_manifest, source),
        "split_counts": source["split_counts"],
        "started_at_utc": "2026-07-14T00:00:00Z",
    }
    manifest_path = root / "manifest.json"
    _ = manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    return manifest_path


def _parser_row(template: dict[str, JsonValue]) -> dict[str, JsonValue]:
    span_count = _integer(template, "expected_span_count")
    semantics = _integer(template, "expected_semantic_result_count")
    text = _text(template, "text")
    characters = list(text)
    spans: list[JsonValue] = []
    for span_index in range(span_count):
        raw = characters[span_index]
        start = len("".join(characters[:span_index]).encode())
        semantic_count = 1 + (semantics - span_count if span_index == 0 else 0)
        spans.append(
            {
                "end_byte": start + len(raw.encode()),
                "raw": raw,
                "semantics": [
                    _semantic(span_index, index) for index in range(semantic_count)
                ],
                "start_byte": start,
            }
        )
    return {
        "row_id": template["row_id"],
        "spans": spans,
        "split": template["split"],
        "stratum": template["stratum"],
        "supported": span_count > 0,
        "text": text,
    }


def _assessor_rows(
    templates: tuple[dict[str, JsonValue], ...],
    context: _StrictFixtureContext,
    slot: str,
) -> tuple[dict[str, JsonValue], ...]:
    rows: list[dict[str, JsonValue]] = []
    for template in templates:
        pair = _pair(template)
        anchor_id, candidate_id = _strict_pair(pair, context.unrelated)
        label = context.labels[pair]
        if slot == "b" and pair in context.disagreements:
            label = (label + 1) % 4
        rows.append(
            {
                "anchor_id": anchor_id,
                "assessor_id": "alpha" if slot == "a" else "beta",
                "blinded_ordinal": template["blinded_ordinal"],
                "candidate_id": candidate_id,
                "label_0_3": label,
                "reason": "fixture",
                "split": context.pool[pair]["split"],
            }
        )
    return tuple(rows)


def _adjudication_rows(
    pool: dict[tuple[str, str], dict[str, JsonValue]],
    labels: dict[tuple[str, str], int],
    disagreements: set[tuple[str, str]],
    unrelated: bool,
) -> tuple[dict[str, JsonValue], ...]:
    rows: list[dict[str, JsonValue]] = []
    for pair in sorted(disagreements):
        anchor_id, candidate_id = _strict_pair(pair, unrelated)
        label_a = labels[pair]
        rows.append(
            {
                "adjudicator_id": "gamma",
                "anchor_id": anchor_id,
                "candidate_id": candidate_id,
                "final_label": (label_a + 2) % 4,
                "label_a": label_a,
                "label_b": (label_a + 1) % 4,
                "reason": "adjudicated",
                "split": pool[pair]["split"],
            }
        )
    return tuple(rows)


def _gold_rows(
    pool: tuple[dict[str, JsonValue], ...],
    labels: dict[tuple[str, str], int],
    disagreements: set[tuple[str, str]],
    unrelated: bool,
) -> tuple[dict[str, JsonValue], ...]:
    rows: list[dict[str, JsonValue]] = []
    for source_row in pool:
        pair = _pair(source_row)
        anchor_id, candidate_id = _strict_pair(pair, unrelated)
        label = labels[pair]
        rows.append(
            {
                "anchor_id": anchor_id,
                "candidate_id": candidate_id,
                "final_label": (label + 2) % 4 if pair in disagreements else label,
                "reason": "fixture",
                "split": source_row["split"],
            }
        )
    return tuple(rows)


def _source_identity(path: Path, source: dict[str, JsonValue]) -> dict[str, JsonValue]:
    release = source["release"]
    assert isinstance(release, dict)
    return {
        **release,
        "export_id": source["export_id"],
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parser_template_sha256": source["parser_template_sha256"],
    }


def _load_rows(path: Path) -> tuple[dict[str, JsonValue], ...]:
    return tuple(
        JSON_ADAPTER.validate_json(line) for line in path.read_bytes().splitlines()
    )


def _pair(row: dict[str, JsonValue]) -> tuple[str, str]:
    return _text(row, "anchor_id"), _text(row, "candidate_id")


def _strict_pair(pair: tuple[str, str], unrelated: bool) -> tuple[str, str]:
    if not unrelated:
        return pair
    return f"A-{pair[0]}", f"A-{pair[1]}"


def _text(row: dict[str, JsonValue], key: str) -> str:
    value = row[key]
    assert isinstance(value, str)
    return value


def _integer(row: dict[str, JsonValue], key: str) -> int:
    value = row[key]
    assert isinstance(value, int)
    return value


def _semantic(span_index: int, semantic_index: int) -> dict[str, JsonValue]:
    return {
        "attribute_key": f"attribute-{semantic_index}",
        "canonical_unit": "V" if span_index == 0 else "A",
        "dimension": f"dimension-{semantic_index}",
        "lower": None,
        "relation": "eq",
        "upper": None,
        "value_decimal": "1",
    }


def _jsonl(rows: tuple[dict[str, JsonValue], ...]) -> bytes:
    if not rows:
        return b""
    return ("\n".join(canonical_json(row) for row in rows) + "\n").encode()
