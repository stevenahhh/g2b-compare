"""Explicit synthetic artifacts used only to test the strict runner boundary."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.evaluation.e0_export import export_e0
from g2b_compare.evaluation.runner import StrictEvaluationPaths

from .e0_fixture import release_fixture
from .e0_strict_fixture import write_strict_package

if TYPE_CHECKING:
    from pathlib import Path

JSON_ADAPTER = TypeAdapter(dict[str, JsonValue])


def strict_runner_paths(root: Path) -> StrictEvaluationPaths:
    """Create labels only inside an explicitly synthetic test fixture."""
    source_root = root / "source"
    _ = export_e0(release_fixture(), source_root, seed="20260714")
    source = source_root / "manifest.json"
    manifest = write_strict_package(root / "strict", source)
    gold = _load(manifest.parent / "gold-v1.jsonl")
    parser_gold = _load(manifest.parent / "parser-gold-v1.jsonl")
    full = root / "full-v1.predictions.jsonl"
    lexical = root / "lexical-only.predictions.jsonl"
    parser = root / "parser.predictions.jsonl"
    by_anchor: dict[str, list[dict[str, JsonValue]]] = defaultdict(list)
    for row in gold:
        by_anchor[_text(row, "anchor_id")].append(row)
    full_rows: list[dict[str, JsonValue]] = []
    lexical_rows: list[dict[str, JsonValue]] = []
    for rows in by_anchor.values():
        for ordinal, row in enumerate(rows):
            base = {
                "anchor_id": row["anchor_id"],
                "candidate_id": row["candidate_id"],
                "category_match": True,
            }
            full_rows.append({**base, "score": str(row["final_label"])})
            lexical_rows.append({**base, "score": str(10 - ordinal)})
    _write(full, full_rows)
    _write(lexical, lexical_rows)
    _write(
        parser,
        [{"row_id": row["row_id"], "spans": row["spans"]} for row in parser_gold],
    )
    return StrictEvaluationPaths(manifest, source, full, lexical, parser)


def rewrite_rows(path: Path, rows: list[dict[str, JsonValue]]) -> None:
    _write(path, rows)


def load_rows(path: Path) -> list[dict[str, JsonValue]]:
    return list(_load(path))


def _load(path: Path) -> tuple[dict[str, JsonValue], ...]:
    return tuple(
        JSON_ADAPTER.validate_json(line) for line in path.read_bytes().splitlines()
    )


def _write(path: Path, rows: list[dict[str, JsonValue]]) -> None:
    payload = "\n".join(canonical_json(row) for row in rows) + "\n"
    _ = path.write_text(payload, encoding="utf-8")


def _text(row: dict[str, JsonValue], key: str) -> str:
    value = row[key]
    assert isinstance(value, str)
    return value
