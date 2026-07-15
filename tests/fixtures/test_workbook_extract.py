from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
FIXTURES = ROOT / "tests" / "fixtures"
EXTRACTOR = ROOT / "tools" / "extract_workbook_fixtures.py"
RELATION_SHA256 = "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db"
SOURCE_HASHES = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in DATASET.glob("*.xlsx")
}


def _run_extract(
    output: Path,
    manifest: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(EXTRACTOR),
        "--source-dir",
        str(DATASET),
        "--output-dir",
        str(output),
    ]
    if manifest is not None:
        command.extend(("--expected-manifest", str(manifest), "--verify-only"))
    return subprocess.run(  # noqa: S603 - command is the fixed local extractor.
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _symlink_or_skip(link: Path, target: Path, *, is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except OSError as error:
        pytest.skip(f"symbolic links unavailable: {error}")


def test_extract_real_workbooks_is_deterministic_and_read_only(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_run = _run_extract(first)
    second_run = _run_extract(second)

    assert first_run.returncode == 0, first_run.stderr
    assert second_run.returncode == 0, second_run.stderr
    first_files = {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert first_files == {
        path.relative_to(FIXTURES): path.read_bytes()
        for path in FIXTURES.rglob("*.json")
        if path.name != "test_workbook_extract.py"
    }
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in DATASET.glob("*.xlsx")
    } == SOURCE_HASHES


def test_extract_rejects_preexisting_hardlink_target(tmp_path: Path) -> None:
    output = tmp_path / "output"
    workbooks = output / "workbooks"
    workbooks.mkdir(parents=True)
    victim = tmp_path / "outside-victim.bin"
    _ = victim.write_bytes(b"outside-content\n")
    target = workbooks / "manifest-v1.json"
    os.link(victim, target)
    before = _sha256(victim)

    result = _run_extract(output)

    assert result.returncode == 1
    assert "hard link" in result.stderr
    assert _sha256(victim) == before
    assert target.samefile(victim)
    assert list(output.rglob("*.tmp")) == []


def test_extract_rejects_preexisting_symlink_target(tmp_path: Path) -> None:
    output = tmp_path / "output"
    workbooks = output / "workbooks"
    workbooks.mkdir(parents=True)
    victim = tmp_path / "outside-victim.bin"
    _ = victim.write_bytes(b"outside-content\n")
    target = workbooks / "manifest-v1.json"
    _symlink_or_skip(target, victim, is_directory=False)
    before = _sha256(victim)

    result = _run_extract(output)

    assert result.returncode == 1
    assert "symbolic link or reparse point" in result.stderr
    assert _sha256(victim) == before
    assert target.is_symlink()
    assert list(output.rglob("*.tmp")) == []


def test_extract_rejects_redirected_output_parent(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected_parent = output / "workbooks"
    _symlink_or_skip(redirected_parent, outside, is_directory=True)

    result = _run_extract(output)

    assert result.returncode == 1
    assert "symbolic link or reparse point" in result.stderr
    assert list(outside.iterdir()) == []
    assert list(output.rglob("*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_extract_rejects_junction_in_output_ancestors(tmp_path: Path) -> None:
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    _ = sentinel.write_bytes(b"outside-content\n")
    before = _sha256(sentinel)
    junction = inside / "redirect"
    command = Path(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"))
    created = subprocess.run(  # noqa: S603 - fixed local test setup.
        [command, "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr}")
    try:
        result = _run_extract(junction / "claimed-output")
    finally:
        junction.rmdir()

    assert result.returncode == 1
    assert "symbolic link or reparse point" in result.stderr
    assert _sha256(sentinel) == before
    assert set(outside.iterdir()) == {sentinel}


def test_manifest_pins_machine_readable_relation_grammar() -> None:
    manifest = (FIXTURES / "workbooks" / "manifest-v1.json").read_text(encoding="utf-8")

    for expected in (
        '"relation_grammar": {',
        '"schema_version": "workbook-relations-v1"',
        f'"source_sha256": "{RELATION_SHA256}"',
        '"sheet": "자재내역서"',
        '"coordinate": "B8"',
        '"coordinate": "B10"',
        '"coordinate": "B26"',
        '"coordinate": "N9"',
        '"value": "24684676"',
        '"curated_relationship_count": 12',
        '"unbound_option_count": 3',
        '"product_id_pattern": "\\\\A[0-9]{8}\\\\Z"',
    ):
        assert expected in manifest


@pytest.mark.parametrize(
    ("indent", "field", "replacement", "message"),
    [
        (6, "sha256", "0" * 64, "source workbook SHA changed"),
        (8, "formula_cells", -1, "workbook formula count changed"),
        (8, "external_links", -1, "workbook external link count changed"),
        (8, "curated_relationships", -1, "workbook relationship count changed"),
        (4, "schema_version", "drift", "workbook manifest changed"),
        (4, "source_sha256", "0" * 64, "workbook manifest changed"),
        (4, "curated_relationship_count", -1, "workbook manifest changed"),
    ],
)
def test_verify_manifest_fails_closed_on_drift(
    tmp_path: Path,
    indent: int,
    field: str,
    replacement: str | int,
    message: str,
) -> None:
    source = FIXTURES / "workbooks" / "manifest-v1.json"
    manifest, replacements = re.subn(
        rf'(?m)^( {{{indent}}}"{field}":\s*)[^,\n]+',
        rf"\g<1>{json.dumps(replacement)}",
        source.read_text(encoding="utf-8"),
        count=1,
    )
    assert replacements == 1
    changed = tmp_path / "manifest-v1.json"
    _ = changed.write_text(manifest, encoding="utf-8")

    result = _run_extract(tmp_path / "unused", changed)

    assert result.returncode == 1
    assert message in result.stderr
