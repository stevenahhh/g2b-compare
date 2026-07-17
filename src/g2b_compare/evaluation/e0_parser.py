"""Deterministic parser-template source classifier and selector."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from g2b_compare.db.hashes import JsonValue, canonical_json

from .e0_models import E0ExportBlocked, E0Split, ParserSource

PARSER_STRATA: Final = (
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
DOMAIN_UNITS: Final = ("MP", "fps", "TB", "GB", "채널", "화소")
PARSER_ROWS: Final = 50
COMPOUND_QUANTITIES: Final = 2
PARSER_TRAIN_ROWS: Final = 30
PARSER_VALIDATION_END: Final = 40
NUMBER: Final = r"[-+]?\d+(?:[.,]\d+)?"
QUANTITY_RE: Final = re.compile(
    rf"(?P<number>{NUMBER})\s*(?P<unit>MP|fps|TB|GB|채널|화소|[kMGm]?(?:V|W|Hz|B))"
)
DETECTOR_PATTERNS: Final = (
    rf"dimension:{NUMBER}\s*[xX\u00d7*]\s*{NUMBER}\s*(?:화소|px|pixel)",
    rf"range:{NUMBER}\s*(?:~|\u2013|-|to)\s*{NUMBER}",
    rf"relation:{NUMBER}\s*(?:MP|fps|TB|GB|채널|화소|[kMGm]?(?:V|W|Hz|B))?\s*(?:이하|이상|미만|초과|<=|>=|<|>)",
    r"arabic-man:\d[\d,]*(?:\.\d+)?\s*만",
    r"decimal-comma:\d,\d",
    r"si-case:(?:k|M|G|m)(?:V|W|Hz|B)",
)
COMPILED: Final = tuple(re.compile(item.split(":", 1)[1]) for item in DETECTOR_PATTERNS)


@dataclass(frozen=True, slots=True)
class ParserTemplate:
    """Unlabeled rows plus stratum-derived annotation target counts."""

    rows: tuple[dict[str, JsonValue], ...]
    positive_spans: int
    semantic_results: int
    negative_rows: int


def build_parser_template(
    sources: tuple[ParserSource, ...], seed: str
) -> ParserTemplate:
    """Return exact ten-by-fifty deterministic unlabeled template rows."""
    first_by_text: dict[str, ParserSource] = {}
    for source in sorted(sources, key=_source_key):
        normalized = unicodedata.normalize("NFKC", source.text.replace("\r\n", "\n"))
        if normalized:
            _ = first_by_text.setdefault(normalized, source)
    grouped: defaultdict[str, list[tuple[ParserSource, str]]] = defaultdict(list)
    for text, source in first_by_text.items():
        detected = _classify(text)
        if detected is not None:
            grouped[detected].append((source, text))
    rows: list[dict[str, JsonValue]] = []
    for stratum in PARSER_STRATA:
        candidates = sorted(
            grouped[stratum],
            key=lambda item: (
                _selection_hash(seed, stratum, *item),
                _source_key(item[0]),
            ),
        )
        if len(candidates) < PARSER_ROWS:
            detail = f"parser stratum {stratum} has {len(candidates)} rows"
            raise E0ExportBlocked(detail)
        selected = candidates[:PARSER_ROWS]
        row_ids = tuple(
            f"PARSER-{stratum}-{index:03d}" for index in range(1, PARSER_ROWS + 1)
        )
        split_by_id = _parser_splits(row_ids, seed)
        for row_id, (source, text) in zip(row_ids, selected, strict=True):
            expected_spans, expected_semantics = _expected_counts(stratum)
            rows.append(
                {
                    "expected_semantic_result_count": expected_semantics,
                    "expected_span_count": expected_spans,
                    "row_id": row_id,
                    "source": {
                        "field_kind": source.field_kind,
                        "ordinal": source.ordinal,
                        "product_id": source.product_id,
                        "source_key": source.source_key,
                    },
                    "spans": [],
                    "split": split_by_id[row_id],
                    "stratum": stratum,
                    "text": text,
                }
            )
    return ParserTemplate(
        tuple(rows),
        sum(_required_int(row, "expected_span_count") for row in rows),
        sum(_required_int(row, "expected_semantic_result_count") for row in rows),
        sum(row["stratum"] == "zero-negative-unsupported" for row in rows),
    )


def detector_sha256() -> str:
    """Hash the versioned priority detector definition."""
    return _sha(canonical_json(list(DETECTOR_PATTERNS)))


def domain_units_sha256() -> str:
    """Hash the versioned domain unit set."""
    return _sha(canonical_json(list(DOMAIN_UNITS)))


def _classify(text: str) -> str | None:
    quantities = tuple(QUANTITY_RE.finditer(text))
    dimensions = {_dimension(item.group("unit")) for item in quantities}
    checks = (
        (
            "compound-mixed",
            len(quantities) == COMPOUND_QUANTITIES
            and len(dimensions) == COMPOUND_QUANTITIES,
        ),
        (
            "zero-negative-unsupported",
            any(_numeric(item.group("number")) <= 0 for item in quantities),
        ),
        ("dimension", COMPILED[0].search(text) is not None),
        ("range", COMPILED[1].search(text) is not None),
        ("relation", COMPILED[2].search(text) is not None),
        ("arabic-man", COMPILED[3].search(text) is not None),
        ("decimal-comma", COMPILED[4].search(text) is not None),
        ("si-case", COMPILED[5].search(text) is not None),
        ("domain-unit", any(unit in text for unit in DOMAIN_UNITS)),
        ("scalar", bool(quantities)),
    )
    return next((stratum for stratum, matched in checks if matched), None)


def _dimension(unit: str) -> str:
    if unit in {"MP", "화소"}:
        return "resolution"
    if unit == "fps":
        return "frame-rate"
    if unit in {"TB", "GB", "B"}:
        return "storage"
    if unit == "채널":
        return "channel"
    return "electrical"


def _numeric(raw: str) -> float:
    return float(raw.replace(",", ""))


def _expected_counts(stratum: str) -> tuple[int, int]:
    if stratum == "zero-negative-unsupported":
        return 0, 0
    if stratum == "compound-mixed":
        return 2, 2
    if stratum == "dimension":
        return 1, 3
    return 1, 1


def _required_int(row: dict[str, JsonValue], key: str) -> int:
    value = row[key]
    if not isinstance(value, int):
        detail = f"parser template field {key} is not integer"
        raise E0ExportBlocked(detail)
    return value


def _source_key(source: ParserSource) -> tuple[str, str, str, int]:
    return source.product_id, source.field_kind, source.source_key, source.ordinal


def _selection_hash(seed: str, stratum: str, source: ParserSource, text: str) -> str:
    fields = (seed, stratum, *_source_key(source), text)
    return _sha("|".join(str(item) for item in fields))


def _parser_splits(row_ids: tuple[str, ...], seed: str) -> dict[str, E0Split]:
    ordered = sorted(row_ids, key=lambda row_id: (_sha(f"{seed}|{row_id}"), row_id))
    result: dict[str, E0Split] = {}
    for index, row_id in enumerate(ordered):
        result[row_id] = (
            "train"
            if index < PARSER_TRAIN_ROWS
            else "validation"
            if index < PARSER_VALIDATION_END
            else "test"
        )
    return result


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
