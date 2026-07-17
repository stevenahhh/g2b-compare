"""Todo 12 E0 immutable export contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from tools.export_e0 import DEFAULT_DATABASE, DEFAULT_SEED, main, parse_arguments

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.evaluation.e0_export import E0ExportBlocked, export_e0
from g2b_compare.evaluation.e0_package import publish_package
from g2b_compare.evaluation.e0_schema import validate_e0_package

from .e0_fixture import release_fixture

JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


def test_export_is_exact_blinded_unlabeled_and_byte_stable(tmp_path: Path) -> None:
    # Given: a frozen release with ten eligible groups and all parser strata
    release = release_fixture(groups=11)
    first = tmp_path / "first"
    second = tmp_path / "second"

    # When: the same release is exported twice
    first_report = export_e0(release, first, seed="20260714")
    second_report = export_e0(release, second, seed="20260714")

    # Then: exact counts, split isolation, blinding, and immutable bytes hold
    assert first_report.anchor_count == 200
    assert first_report.pair_count == 2_000
    assert first_report.parser_row_count == 500
    assert first_report.split_counts == {"test": 40, "train": 120, "validation": 40}
    assert first_report.manifest_sha256 == second_report.manifest_sha256
    assert _tree(first) == _tree(second)
    manifest = _json_object(first / "manifest.json")
    counts = _json_object_value(manifest, "counts")
    files = _json_object_value(manifest, "files")
    parser_file = _json_object_value(files, "parser.template.jsonl")
    group_counts = _json_object_value(manifest, "group_counts")
    assert manifest["started_at_utc"] == "2026-07-14T00:00:00Z"
    assert manifest["completed_at_utc"] == "2026-07-14T00:00:00Z"
    assert counts["parser_positive_spans"] == 500
    assert counts["parser_semantic_results"] == 600
    assert counts["parser_negative_rows"] == 50
    assert parser_file["record_count"] == 500
    assert parser_file["schema_version"] == "parser-template-v1"
    assert manifest["parser_template_sha256"] == parser_file["sha256"]
    assert len(group_counts) == 10
    assert all(
        _json_object_value(group_counts, key)["anchor_count"] == 20
        and _json_object_value(group_counts, key)["pair_count"] == 200
        for key in group_counts
    )
    validation = validate_e0_package(first / "manifest.json")
    assert validation.schema_version == "e0-export-v1"
    pool = _jsonl(first / "pool.jsonl")
    assert len({(row["anchor_id"], row["candidate_id"]) for row in pool}) == 2_000
    assert all("label" not in key for row in pool for key in row)
    assessor = _jsonl(first / "assessor-a.template.jsonl")
    assert all(
        set(row) == {"anchor_id", "assessor_slot", "blinded_ordinal", "candidate_id"}
        for row in assessor
    )
    assert all("label" not in key for row in assessor for key in row)


def test_export_blocks_when_exact_name_pool_has_only_nine_candidates(
    tmp_path: Path,
) -> None:
    # Given: every exact-name pool has only nine candidates per anchor
    release = release_fixture(pool_size=10)

    # When/Then: group eligibility cannot be fabricated across product names
    with pytest.raises(E0ExportBlocked, match="eligible group"):
        _ = export_e0(release, tmp_path / "blocked", seed="20260714")


def test_export_excludes_inactive_rows_before_group_and_lane_selection(
    tmp_path: Path,
) -> None:
    # Given: one group loses one member to inactive state
    release = release_fixture(groups=11)
    products = tuple(
        replace(product, active=False) if product.product_id == "P-00-000" else product
        for product in release.products
    )

    # When: the eligible corpus is exported
    report = export_e0(
        replace(release, products=products),
        tmp_path / "inactive",
        seed="20260714",
    )

    # Then: the inactive product never enters an anchor or candidate lane
    assert report.anchor_count == 200
    payload = (tmp_path / "inactive" / "pool.jsonl").read_text(encoding="utf-8")
    assert "P-00-000" not in payload


def test_export_uses_exact_name_pool_not_mixed_category_names(tmp_path: Path) -> None:
    # Given: one category has two names with ten products each
    release = release_fixture()
    products = tuple(
        replace(product, product_name_key="다른이름")
        if product.product_id.startswith("P-00-") and int(product.product_id[-3:]) >= 10
        else product
        for product in release.products
    )

    # When/Then: neither ten-row name reaches the ten-candidate threshold
    with pytest.raises(E0ExportBlocked, match="eligible group"):
        _ = export_e0(
            replace(release, products=products),
            tmp_path / "mixed",
            seed="20260714",
        )


def test_export_backfills_inactive_lanes_without_duplicate_pairs(
    tmp_path: Path,
) -> None:
    # Given: missing-attribute anchors have no structured lane
    release = release_fixture()

    # When: the pool is exported
    _ = export_e0(release, tmp_path / "lanes", seed="20260714")

    # Then: each anchor still has ten unique rows and explicit backfill ownership
    rows = _jsonl(tmp_path / "lanes" / "pool.jsonl")
    anchor_rows = [row for row in rows if row["anchor_id"] == "P-00-000"]
    assert len(anchor_rows) == 10
    assert len({_row_text(row, "candidate_id") for row in anchor_rows}) == 10
    assert "backfill" in {_row_text(row, "lane") for row in anchor_rows}


def test_parser_template_deduplicates_text_and_blocks_stratum_forty_nine(
    tmp_path: Path,
) -> None:
    # Given: duplicate normalized source text and then one missing unique scalar row
    release = release_fixture()
    duplicate = replace(release.parser_sources[0], source_key="ZZZ", ordinal=999)
    deduped = replace(release, parser_sources=(*release.parser_sources, duplicate))
    missing = replace(release, parser_sources=release.parser_sources[1:])

    # When: the duplicate corpus is exported
    report = export_e0(deduped, tmp_path / "dedupe", seed="20260714")

    # Then: first-source order wins, while an exact 49 stratum blocks export
    assert report.parser_row_count == 500
    with pytest.raises(E0ExportBlocked, match="parser stratum"):
        _ = export_e0(missing, tmp_path / "missing", seed="20260714")


def test_export_rejects_expected_bundle_version_drift(tmp_path: Path) -> None:
    # Given: a caller pinned a different bundle SHA
    release = release_fixture()

    # When/Then: export fails before writing a mixed-version package
    with pytest.raises(E0ExportBlocked, match="bundle version"):
        _ = export_e0(
            release,
            tmp_path / "drift",
            seed="20260714",
            expected_bundle_sha="9" * 64,
        )
    assert not (tmp_path / "drift").exists()


def test_export_refuses_to_mutate_an_existing_immutable_package(tmp_path: Path) -> None:
    # Given: a complete immutable package followed by an identical replay
    release = release_fixture()
    output = tmp_path / "immutable"
    _ = export_e0(release, output, seed="20260714")
    before = _tree(output)

    # When/Then: the replay is rejected and every existing byte is preserved
    with pytest.raises(E0ExportBlocked, match="already exists"):
        _ = export_e0(release, output, seed="20260714")
    assert _tree(output) == before


def test_export_uses_canonical_jsonl_with_exactly_one_final_lf(tmp_path: Path) -> None:
    # Given: one valid frozen release
    output = tmp_path / "canonical"

    # When: its immutable package is exported
    _ = export_e0(release_fixture(), output, seed="20260714")

    # Then: every JSON line is compact sorted-key UTF-8 with one final LF
    for path in sorted(output.glob("*.jsonl")):
        payload = path.read_bytes()
        assert payload.endswith(b"\n")
        assert not payload.endswith(b"\n\n")
        for line in payload.splitlines():
            parsed = JSON_OBJECT_ADAPTER.validate_json(line)
            expected = canonical_json(parsed).encode()
            assert line == expected


def test_export_cli_has_stable_defaults_and_typed_io_exit(tmp_path: Path) -> None:
    # Given: the public CLI parser and a missing database path
    output = tmp_path / "out"
    args = parse_arguments(["--release-bundle", "7", "--out", str(output)])

    # When: defaults are inspected and the missing database is executed
    exit_code = main(
        [
            "--database",
            str(tmp_path / "missing" / "db.sqlite3"),
            "--release-bundle",
            "7",
            "--out",
            str(output),
        ]
    )

    # Then: documented defaults and the I/O exit class stay machine-readable
    assert args.database == DEFAULT_DATABASE
    assert args.seed == DEFAULT_SEED
    assert exit_code == 3
    assert not output.exists()


@pytest.mark.parametrize("failure", ["write", "rename"])
def test_atomic_publication_cleans_staging_on_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    # Given: an injected mid-publication filesystem failure
    output = tmp_path / "package"
    original_write = Path.write_bytes
    original_replace = Path.replace

    def fail_write(path: Path, payload: bytes) -> int:
        if failure == "write" and path.name == "second.jsonl":
            detail = "injected write failure"
            raise OSError(detail)
        return original_write(path, payload)

    def fail_replace(path: Path, target: Path) -> Path:
        if failure == "rename":
            detail = "injected rename failure"
            raise OSError(detail)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    monkeypatch.setattr(Path, "replace", fail_replace)

    # When/Then: publication fails without an output or staging remnant
    with pytest.raises(OSError, match="injected"):
        publish_package(output, {"first.jsonl": b"1\n", "second.jsonl": b"2\n"})
    assert not output.exists()
    assert not tuple(tmp_path.glob(".package.*"))


def _jsonl(path: Path) -> list[dict[str, JsonValue]]:
    return [
        JSON_OBJECT_ADAPTER.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _json_object(path: Path) -> dict[str, JsonValue]:
    return JSON_OBJECT_ADAPTER.validate_json(path.read_bytes())


def _json_object_value(row: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = row[key]
    assert isinstance(value, dict)
    return value


def _row_text(row: dict[str, JsonValue], key: str) -> str:
    value = row[key]
    assert isinstance(value, str)
    return value


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
