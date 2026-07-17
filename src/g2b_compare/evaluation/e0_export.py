"""Immutable E0 pool and blinded-template export from a frozen release."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from g2b_compare.db.hashes import JsonValue, canonical_json, sha256_text

from .e0_lanes import PoolBuildContext, build_pool_rows
from .e0_models import (
    E0ExportBlocked,
    E0ExportReport,
    E0Product,
    FrozenE0Release,
    ParserSource,
    ReleaseIdentity,
)
from .e0_package import (
    ManifestSelection,
    build_manifest,
    publish_package,
    serialize_jsonl,
    serialize_manifest,
    sha256_bytes,
)
from .e0_parser import build_parser_template

if TYPE_CHECKING:
    from pathlib import Path

STRATA: Final = (
    "missing-attributes",
    "missing-price",
    "model-number",
    "mixed-Korean-Latin",
    "Korean-only-other",
)
MODEL_TOKEN: Final[re.Pattern[str]] = re.compile(r"[^\W_]+(?:[-_/][^\W_]+)*")
EXACT_POOL_SIZE: Final = 11
ANCHORS_PER_STRATUM: Final = 4
GROUP_COUNT: Final = 10
TRAIN_GROUPS: Final = 6
VALIDATION_END: Final = 8
CONNECTED_PARTS: Final = 2
ANCHORS_PER_GROUP: Final = 20

__all__ = [
    "E0ExportBlocked",
    "E0Product",
    "FrozenE0Release",
    "ParserSource",
    "ReleaseIdentity",
    "export_e0",
]


def export_e0(
    release: FrozenE0Release,
    output: Path,
    *,
    seed: str,
    expected_bundle_sha: str | None = None,
) -> E0ExportReport:
    """Apply the strict prerequisite and atomically publish unlabeled bytes."""
    if (
        expected_bundle_sha is not None
        and release.identity.release_bundle_sha != expected_bundle_sha
    ):
        detail = "bundle version drift"
        raise E0ExportBlocked(detail)
    exact_pools = _exact_pools(release.products)
    anchors, splits, stratum_counts = _anchors(exact_pools, seed)
    anchor_strata = {
        anchor.product_id: stratum
        for anchor in anchors
        if (stratum := _stratum(anchor)) is not None
    }
    pool = build_pool_rows(
        anchors,
        PoolBuildContext(exact_pools, splits, anchor_strata, release.identity, seed),
    )
    parser = build_parser_template(release.parser_sources, seed)
    assessor_a = _assessor_rows(pool, "a", seed)
    assessor_b = _assessor_rows(pool, "b", seed)
    payloads = {
        "assessor-a.template.jsonl": serialize_jsonl(assessor_a),
        "assessor-b.template.jsonl": serialize_jsonl(assessor_b),
        "parser.template.jsonl": serialize_jsonl(parser.rows),
        "pool.jsonl": serialize_jsonl(pool),
    }
    split_counts = dict(sorted(Counter(splits.values()).items()))
    split_anchor_counts = {
        name: count * ANCHORS_PER_GROUP for name, count in split_counts.items()
    }
    manifest = build_manifest(
        release,
        payloads,
        ManifestSelection(
            seed,
            splits,
            stratum_counts,
            split_anchor_counts,
            parser.positive_spans,
            parser.semantic_results,
            parser.negative_rows,
        ),
    )
    manifest_payload = serialize_manifest(manifest)
    publish_package(output, {**payloads, "manifest.json": manifest_payload})
    return E0ExportReport(
        manifest_sha256=sha256_bytes(manifest_payload),
        anchor_count=len(anchors),
        pair_count=len(pool),
        parser_row_count=len(parser.rows),
        split_counts=split_anchor_counts,
    )


def _exact_pools(
    products: tuple[E0Product, ...],
) -> dict[tuple[str, str, str], tuple[E0Product, ...]]:
    grouped: defaultdict[tuple[str, str, str], list[E0Product]] = defaultdict(list)
    for product in products:
        if product.active:
            grouped[(*product.category_tuple, product.product_name_key)].append(product)
    return {
        key: tuple(sorted(values, key=lambda item: item.product_id))
        for key, values in grouped.items()
    }


def _anchors(
    exact_pools: dict[tuple[str, str, str], tuple[E0Product, ...]], seed: str
) -> tuple[tuple[E0Product, ...], dict[tuple[str, str], str], dict[str, int]]:
    eligible_by_group: defaultdict[tuple[str, str], list[E0Product]] = defaultdict(list)
    for pool in exact_pools.values():
        if len(pool) >= EXACT_POOL_SIZE:
            eligible_by_group[pool[0].category_tuple].extend(pool)
    valid: list[tuple[tuple[str, str], tuple[E0Product, ...]]] = []
    for group, products in eligible_by_group.items():
        classified = _classified(tuple(products))
        if all(len(classified[stratum]) >= ANCHORS_PER_STRATUM for stratum in STRATA):
            valid.append((group, tuple(products)))
    valid.sort(key=lambda item: (-len(item[1]), item[0]))
    if len(valid) < GROUP_COUNT:
        detail = f"eligible group count is {len(valid)}, expected {GROUP_COUNT}"
        raise E0ExportBlocked(detail)
    selected = valid[:GROUP_COUNT]
    group_order = sorted(
        (group for group, _ in selected),
        key=lambda group: (sha256_text(f"{seed}|{_category_json(group)}"), group),
    )
    splits = {
        group: (
            "train"
            if index < TRAIN_GROUPS
            else "validation"
            if index < VALIDATION_END
            else "test"
        )
        for index, group in enumerate(group_order)
    }
    anchors: list[E0Product] = []
    for _, products in selected:
        classified = _classified(products)
        for stratum in STRATA:
            anchors.extend(
                sorted(
                    classified[stratum],
                    key=lambda item: (
                        sha256_text(f"{seed}|{item.product_id}"),
                        item.product_id,
                    ),
                )[:ANCHORS_PER_STRATUM]
            )
    return tuple(anchors), splits, dict.fromkeys(STRATA, 40)


def _classified(products: tuple[E0Product, ...]) -> dict[str, tuple[E0Product, ...]]:
    output: defaultdict[str, list[E0Product]] = defaultdict(list)
    for product in products:
        stratum = _stratum(product)
        if stratum is not None:
            output[stratum].append(product)
    return {name: tuple(output[name]) for name in STRATA}


def _stratum(product: E0Product) -> str | None:
    if product.attribute_count == 0:
        return "missing-attributes"
    if (
        product.price_won is None
        or product.price_won <= 0
        or product.price_unit is None
    ):
        return "missing-price"
    if _has_model_number(product.option_text):
        return "model-number"
    has_hangul = any("가" <= char <= "힣" for char in product.option_text)
    has_latin = any(_is_latin(char) for char in product.option_text)
    if has_hangul and has_latin:
        return "mixed-Korean-Latin"
    return "Korean-only-other" if has_hangul and not has_latin else None


def _has_model_number(text: str) -> bool:
    for match in MODEL_TOKEN.finditer(text):
        token = match.group()
        for left, right in pairwise(token):
            if (_is_latin(left) and right.isdigit()) or (
                left.isdigit() and _is_latin(right)
            ):
                return True
        parts = re.split(r"[-_/]", token)
        if (
            len(parts) == CONNECTED_PARTS
            and any(_is_latin(char) for char in parts[0])
            and any(char.isdigit() for char in parts[1])
        ):
            return True
    return False


def _is_latin(char: str) -> bool:
    return unicodedata.name(char, "").startswith("LATIN ")


def _assessor_rows(
    pool: tuple[dict[str, JsonValue], ...], slot: str, seed: str
) -> tuple[dict[str, JsonValue], ...]:
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in pool:
        grouped[_text(row, "anchor_id")].append(_text(row, "candidate_id"))
    rows: list[dict[str, JsonValue]] = []
    for anchor_id in sorted(grouped):
        ordered = sorted(
            grouped[anchor_id],
            key=lambda candidate_id: (
                sha256_text(f"{seed}|{anchor_id}|{candidate_id}"),
                candidate_id,
            ),
        )
        rows.extend(
            {
                "anchor_id": anchor_id,
                "assessor_slot": slot,
                "blinded_ordinal": ordinal,
                "candidate_id": candidate_id,
            }
            for ordinal, candidate_id in enumerate(ordered, start=1)
        )
    return tuple(rows)


def _text(row: dict[str, JsonValue], key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        detail = f"pool field {key} is not text"
        raise E0ExportBlocked(detail)
    return value


def _category_json(group: tuple[str, str]) -> str:
    return canonical_json({"category_no": group[0], "detail_category_no": group[1]})
