"""Exact perf-v1 corpus generation contracts."""

from __future__ import annotations

import hashlib
import inspect
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from g2b_compare.db.hashes import JsonValue
from g2b_compare.evaluation.perf_corpus import (
    THREAD_VARIABLES,
    PerfCorpusResult,
    PerfQueryError,
    generate_perf_corpus,
    validate_perf_queries,
)
from g2b_compare.evaluation.perf_index import PerfIndexError, load_perf_index
from g2b_compare.evaluation.perf_reader import (
    PerfReaderArtifacts,
    PerfSearchReader,
    perf_release_pin,
)


@dataclass(frozen=True, slots=True)
class _Corpora:
    root: Path
    left: PerfCorpusResult
    right: PerfCorpusResult


@pytest.fixture(scope="module")
def perf_corpora(tmp_path_factory: pytest.TempPathFactory) -> _Corpora:
    root = tmp_path_factory.mktemp("perf-v1")
    return _Corpora(
        root,
        generate_perf_corpus(root / "left"),
        generate_perf_corpus(root / "right"),
    )


def test_perf_v1_is_exact_50k_and_byte_deterministic(
    perf_corpora: _Corpora,
) -> None:
    assert perf_corpora.left.product_count == 50_000
    assert perf_corpora.left.query_count == 200
    assert perf_corpora.left.corpus_sha256 == perf_corpora.right.corpus_sha256
    assert perf_corpora.left.query_sha256 == perf_corpora.right.query_sha256
    assert (perf_corpora.root / "left" / "corpus.jsonl").read_bytes() == (
        perf_corpora.root / "right" / "corpus.jsonl"
    ).read_bytes()
    assert (
        hashlib.sha256(
            (perf_corpora.root / "left" / "queries-v1.json").read_bytes()
        ).hexdigest()
        == perf_corpora.left.query_sha256
    )


def test_perf_v1_distribution_and_edge_queries_are_exact(
    perf_corpora: _Corpora,
) -> None:
    result = perf_corpora.left
    corpus = perf_corpora.root / "left"
    rows = TypeAdapter(list[dict[str, JsonValue]]).validate_json(
        (corpus / "queries-v1.json").read_bytes()
    )
    edge = [rows[index] for index in (0, 139, 140, 179, 180, 199)]
    expected = TypeAdapter(list[dict[str, JsonValue]]).validate_json(
        Path("tests/fixtures/performance/queries-v1-edge.json").read_bytes()
    )

    assert result.structured_count == 35_000
    assert result.missing_price_count == 5_000
    assert result.mixed_unit_count == 2_500
    assert result.query_with_spec_count == 180
    assert result.query_with_price_count == 140
    assert edge == expected
    assert (corpus / "queries-v1.sha256").read_text(encoding="ascii").strip() == (
        Path("tests/fixtures/performance/queries-v1.sha256")
        .read_text(encoding="ascii")
        .strip()
    )

    mixed = next(
        line
        for line in (corpus / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
        if '"product_id":"PERF-000-019"' in line
    )
    assert '"price_unit":"식"' in mixed


def test_perf_v1_manifest_records_locked_runtime_and_hardware(
    perf_corpora: _Corpora,
) -> None:
    manifest = (perf_corpora.root / "left" / "manifest.json").read_text(
        encoding="utf-8"
    )

    for field in ("numpy", "python", "scikit-learn", "sqlite"):
        assert f'"{field}":"' in manifest
    for field in ("ram_bytes", "disk_total_bytes", "disk_free_bytes"):
        assert f'"{field}":0' not in manifest
    for name, value in zip(THREAD_VARIABLES, ("0", "1", "1", "1"), strict=True):
        assert f'"{name}":"{value}"' in manifest


def test_perf_v1_publishes_real_consumed_word_and_char_index(
    perf_corpora: _Corpora,
    tmp_path: Path,
) -> None:
    result = perf_corpora.left
    corpus = perf_corpora.root / "left"
    index = corpus / "index.bin"
    manifest = (corpus / "manifest.json").read_text(encoding="utf-8")

    assert index.stat().st_size > 1_000_000
    assert index.read_bytes().startswith(b"PERFIDX1")
    for field in (
        "char_idf_sha256",
        "char_index_sha256",
        "index_manifest_sha256",
        "word_idf_sha256",
        "word_index_sha256",
    ):
        assert f'"{field}":"' in manifest
    assert hashlib.sha256(index.read_bytes()).hexdigest() == result.index_sha256
    assert "index" in inspect.signature(PerfReaderArtifacts).parameters
    loaded = load_perf_index(index)
    assert len(loaded.product_ids) == 50_000

    pin = perf_release_pin(
        database_sha256=result.database_sha256,
        index_sha256=result.index_sha256,
        cache_sha256=result.cache_sha256,
    )
    reader = PerfSearchReader(
        PerfReaderArtifacts(
            corpus / "perf.sqlite3",
            corpus / "comparator-cache.bin",
            index,
        ),
        pin,
        cache_enabled=False,
    )
    assert len(reader.exact_products(pin, "영상감시장치-000")) == 20

    corrupt = tmp_path / "corrupt-index.bin"
    _ = corrupt.write_bytes(index.read_bytes()[:-1])
    with pytest.raises(PerfIndexError, match="perf-index-malformed"):
        _ = load_perf_index(corrupt)
    empty = tmp_path / "empty-index.bin"
    _ = empty.write_bytes(b"")
    with pytest.raises(PerfIndexError, match="perf-index-malformed"):
        _ = load_perf_index(empty)

    tampered_query = tmp_path / "queries-v1.json"
    tampered_receipt = tmp_path / "queries-v1.sha256"
    _ = shutil.copyfile(corpus / "queries-v1.json", tampered_query)
    _ = shutil.copyfile(corpus / "queries-v1.sha256", tampered_receipt)
    payload = tampered_query.read_bytes()
    _ = tampered_query.write_bytes(payload[:-1] + b" ")
    with pytest.raises(PerfQueryError, match="perf-query-hash-drift"):
        validate_perf_queries(tampered_query, tampered_receipt)

    valid_query = tmp_path / "valid-queries-v1.json"
    noncanonical_receipt = tmp_path / "noncanonical.sha256"
    _ = shutil.copyfile(corpus / "queries-v1.json", valid_query)
    receipt = (corpus / "queries-v1.sha256").read_bytes()
    _ = noncanonical_receipt.write_bytes(b"  " + receipt + b"\n")
    with pytest.raises(PerfQueryError, match="perf-query-hash-drift"):
        validate_perf_queries(valid_query, noncanonical_receipt)
    with pytest.raises(PerfQueryError, match="perf-query-hash-drift"):
        validate_perf_queries(valid_query, tmp_path / "missing.sha256")
