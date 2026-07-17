from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue
from g2b_compare.evaluation.e0_export import E0ExportBlocked, export_e0
from g2b_compare.evaluation.e0_package import sha256_bytes
from g2b_compare.evaluation.e0_parser import build_parser_template
from tests.evaluation.e0_fixture import release_fixture

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from g2b_compare.evaluation.e0_models import E0ExportReport
    from g2b_compare.evaluation.e0_parser import ParserTemplate

JSON_OBJECT: Final = TypeAdapter(dict[str, JsonValue])
SEED: Final = "20260714"


def observe_e0(scenario: str, tmp_path: Path) -> tuple[str, str]:
    try:
        handler = _HANDLERS[scenario]
    except KeyError:
        detail = f"unknown E0 scenario: {scenario}"
        raise AssertionError(detail) from None
    return handler(tmp_path)


def _mixed_product_names(tmp_path: Path) -> tuple[str, str]:
    release = release_fixture()
    products = tuple(
        replace(product, product_name_key="다른이름")
        if product.product_id.startswith("P-00-")
        and int(product.product_id[-3:]) >= 10
        else product
        for product in release.products
    )
    return _blocked(
        lambda: export_e0(
            replace(release, products=products),
            tmp_path / "mixed-product-names",
            seed=SEED,
        )
    )


def _exact_name_candidate_nine(tmp_path: Path) -> tuple[str, str]:
    release = release_fixture(pool_size=10)
    return _blocked(
        lambda: export_e0(release, tmp_path / "candidate-nine", seed=SEED)
    )


def _lane_inactive(tmp_path: Path) -> tuple[str, str]:
    release = release_fixture(groups=11)
    inactive_id = "P-00-000"
    products = tuple(
        replace(product, active=False)
        if product.product_id == inactive_id
        else product
        for product in release.products
    )
    output = tmp_path / "lane-inactive"
    report = export_e0(replace(release, products=products), output, seed=SEED)
    rows = _jsonl(output / "pool.jsonl")
    inactive_present = any(
        inactive_id in (_text(row, "anchor_id"), _text(row, "candidate_id"))
        for row in rows
    )
    return type(report).__name__, (
        f"anchors={report.anchor_count}; inactive-present={inactive_present}"
    )


def _lane_dedupe(tmp_path: Path) -> tuple[str, str]:
    output = tmp_path / "lane-dedupe"
    _ = export_e0(release_fixture(), output, seed=SEED)
    rows = _jsonl(output / "pool.jsonl")
    pairs = tuple(
        (_text(row, "anchor_id"), _text(row, "candidate_id")) for row in rows
    )
    counts = Counter(anchor_id for anchor_id, _ in pairs)
    return type(pairs).__name__, (
        f"pairs={len(pairs)}; unique-pairs={len(set(pairs))}; "
        f"anchors={len(counts)}; min-candidates={min(counts.values())}; "
        f"max-candidates={max(counts.values())}"
    )


def _lane_backfill(tmp_path: Path) -> tuple[str, str]:
    release = release_fixture()
    output = tmp_path / "lane-backfill"
    _ = export_e0(release, output, seed=SEED)
    rows = _jsonl(output / "pool.jsonl")
    missing_attribute_ids = {
        product.product_id
        for product in release.products
        if product.attribute_count == 0
    }
    anchor_id = next(
        _text(row, "anchor_id")
        for row in rows
        if _text(row, "anchor_id") in missing_attribute_ids
    )
    anchor_rows = tuple(row for row in rows if _text(row, "anchor_id") == anchor_id)
    candidates = {_text(row, "candidate_id") for row in anchor_rows}
    backfill = sum(_text(row, "lane") == "backfill" for row in anchor_rows)
    return type(anchor_rows).__name__, (
        f"anchor={anchor_id}; unique-candidates={len(candidates)}; backfill={backfill}"
    )


def _bundle_version_drift(tmp_path: Path) -> tuple[str, str]:
    return _blocked(
        lambda: export_e0(
            release_fixture(),
            tmp_path / "bundle-drift",
            seed=SEED,
            expected_bundle_sha="9" * 64,
        )
    )


def _parser_source_order(_: Path) -> tuple[str, str]:
    release = release_fixture()
    original = release.parser_sources[0]
    duplicate = replace(original, source_key="ZZZ", ordinal=999)
    rows = build_parser_template((*release.parser_sources, duplicate), SEED).rows
    row = next(item for item in rows if _text(item, "text") == original.text)
    source = _mapping(row, "source")
    source_key = _text(source, "source_key")
    ordinal = _integer(source, "ordinal")
    return type(source).__name__, (
        f"source-key={source_key}; ordinal={ordinal}"
    )


def _parser_stratum_overlap(_: Path) -> tuple[str, str]:
    rows = build_parser_template(release_fixture().parser_sources, SEED).rows
    row = next(
        item
        for item in rows
        if _text(item, "text").startswith("해상도 8MP 저장 2TB #000")
    )
    return type(row).__name__, (
        f"stratum={_text(row, 'stratum')}; text={_text(row, 'text')}"
    )


def _parser_text_dedup(_: Path) -> tuple[str, str]:
    release = release_fixture()
    duplicate = replace(release.parser_sources[0], source_key="ZZZ", ordinal=999)
    rows = build_parser_template((*release.parser_sources, duplicate), SEED).rows
    texts = tuple(_text(row, "text") for row in rows)
    return type(texts).__name__, f"rows={len(texts)}; unique-texts={len(set(texts))}"


def _parser_stratum_forty_nine(_: Path) -> tuple[str, str]:
    sources = release_fixture().parser_sources[1:]
    return _blocked(lambda: build_parser_template(sources, SEED))


def _parser_template_sha(tmp_path: Path) -> tuple[str, str]:
    first = tmp_path / "parser-sha-first"
    second = tmp_path / "parser-sha-second"
    release = release_fixture()
    _ = export_e0(release, first, seed=SEED)
    _ = export_e0(release, second, seed=SEED)
    first_payload = (first / "parser.template.jsonl").read_bytes()
    second_payload = (second / "parser.template.jsonl").read_bytes()
    digest = sha256_bytes(first_payload)
    manifest = JSON_OBJECT.validate_json((first / "manifest.json").read_bytes())
    files = _mapping(manifest, "files")
    parser_file = _mapping(files, "parser.template.jsonl")
    observation = {
        "stable": first_payload == second_payload,
        "manifest-match": _text(parser_file, "sha256") == digest,
    }
    return type(observation).__name__, (
        f"stable={observation['stable']}; "
        f"manifest-match={observation['manifest-match']}; sha256={digest}"
    )


def _blocked(
    action: Callable[
        [], E0ExportReport | ParserTemplate
    ],
) -> tuple[str, str]:
    try:
        _ = action()
    except E0ExportBlocked as error:
        return type(error).__name__, str(error)
    detail = "E0 scenario unexpectedly succeeded"
    raise AssertionError(detail)


def _jsonl(path: Path) -> tuple[dict[str, JsonValue], ...]:
    return tuple(
        JSON_OBJECT.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _mapping(row: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = row[key]
    assert isinstance(value, dict)
    return value


def _text(row: dict[str, JsonValue], key: str) -> str:
    value = row[key]
    assert isinstance(value, str)
    return value


def _integer(row: dict[str, JsonValue], key: str) -> int:
    value = row[key]
    assert isinstance(value, int)
    return value


_HANDLERS: Final[dict[str, Callable[[Path], tuple[str, str]]]] = {
    "e0-mixed-product-names": _mixed_product_names,
    "e0-exact-name-candidate-nine": _exact_name_candidate_nine,
    "e0-lane-inactive": _lane_inactive,
    "e0-lane-dedupe": _lane_dedupe,
    "e0-lane-backfill": _lane_backfill,
    "e0-bundle-version-drift": _bundle_version_drift,
    "parser-source-order": _parser_source_order,
    "parser-stratum-overlap": _parser_stratum_overlap,
    "parser-text-dedup": _parser_text_dedup,
    "parser-stratum-forty-nine": _parser_stratum_forty_nine,
    "parser-template-sha": _parser_template_sha,
}
