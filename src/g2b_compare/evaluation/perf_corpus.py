"""Generate the exact deterministic perf-v1 product and query population."""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING, Final, override

from g2b_compare.db.hashes import JsonValue, canonical_json

from .perf_index import write_perf_index
from .perf_population import (
    MISSING_PRICE_REMAINDER,
    MIXED_UNIT_REMAINDER,
    POOL_COUNT,
    POOL_SIZES,
    index_products,
    pool_offsets,
    storage_rows,
    write_corpus,
)
from .perf_runtime import LOCKED_THREAD_ENV
from .perf_storage import sqlite3_version, write_perf_cache, write_perf_database

if TYPE_CHECKING:
    from pathlib import Path

SEED: Final = "20260714"
VERSION: Final = "perf-v1"
CREATED_AT: Final = "2026-07-14T00:00:00Z"
QUERY_COUNT: Final = 200
SPEC_QUERY_COUNT: Final = 180
PRICE_QUERY_COUNT: Final = 140
THREAD_VARIABLES: Final = tuple(name for name, _value in LOCKED_THREAD_ENV)
QUERY_HASH_DRIFT: Final = "perf-query-hash-drift"
HEX_DIGITS: Final = frozenset("0123456789abcdef")
SHA256_HEX_LENGTH: Final = 64


@dataclass(frozen=True, slots=True)
class PerfQueryError(Exception):
    """Reject a missing, malformed, or mismatched perf query hash receipt."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class PerfCorpusResult:
    """Immutable receipts and exact distribution counts for one corpus."""

    product_count: int
    query_count: int
    structured_count: int
    missing_price_count: int
    mixed_unit_count: int
    query_with_spec_count: int
    query_with_price_count: int
    corpus_sha256: str
    query_sha256: str
    database_sha256: str
    index_sha256: str
    index_manifest_sha256: str
    word_index_sha256: str
    char_index_sha256: str
    word_idf_sha256: str
    char_idf_sha256: str
    cache_sha256: str


def generate_perf_corpus(output: Path) -> PerfCorpusResult:
    """Publish exact product/query bytes plus queryable benchmark artifacts."""
    output.mkdir(parents=True, exist_ok=False)
    corpus_path = output / "corpus.jsonl"
    counters = write_corpus(corpus_path)
    query_payload = _query_payload()
    query_path = output / "queries-v1.json"
    _ = query_path.write_bytes(query_payload)
    query_sha256 = _sha(query_path)
    query_receipt = output / "queries-v1.sha256"
    _ = query_receipt.write_text(
        query_sha256 + "\n",
        encoding="ascii",
        newline="\n",
    )
    validate_perf_queries(query_path, query_receipt)
    database_path = output / "perf.sqlite3"
    write_perf_database(database_path, storage_rows())
    index_path = output / "index.bin"
    index = write_perf_index(index_path, index_products())
    cache_path = output / "comparator-cache.bin"
    write_perf_cache(cache_path, POOL_SIZES)
    result = PerfCorpusResult(
        product_count=counters[0],
        query_count=QUERY_COUNT,
        structured_count=counters[1],
        missing_price_count=counters[2],
        mixed_unit_count=counters[3],
        query_with_spec_count=SPEC_QUERY_COUNT,
        query_with_price_count=PRICE_QUERY_COUNT,
        corpus_sha256=_sha(corpus_path),
        query_sha256=query_sha256,
        database_sha256=_sha(database_path),
        index_sha256=index.file_sha256,
        index_manifest_sha256=index.manifest_sha256,
        word_index_sha256=index.word_index_sha256,
        char_index_sha256=index.char_index_sha256,
        word_idf_sha256=index.word_idf_sha256,
        char_idf_sha256=index.char_idf_sha256,
        cache_sha256=_sha(cache_path),
    )
    _write_manifest(output / "manifest.json", result)
    return result


def validate_perf_queries(query_path: Path, receipt_path: Path) -> None:
    """Fail closed unless query bytes match one canonical lowercase SHA receipt."""
    try:
        receipt = receipt_path.read_bytes()
        expected = receipt[:-1].decode("ascii")
        actual = _sha(query_path)
    except (OSError, UnicodeError):
        raise PerfQueryError(QUERY_HASH_DRIFT) from None
    if (
        len(receipt) != SHA256_HEX_LENGTH + 1
        or receipt[-1:] != b"\n"
        or len(expected) != SHA256_HEX_LENGTH
        or any(character not in HEX_DIGITS for character in expected)
        or not hmac.compare_digest(actual, expected)
    ):
        raise PerfQueryError(QUERY_HASH_DRIFT)


def _query_payload() -> bytes:
    offsets = pool_offsets()
    rows: list[JsonValue] = []
    for index in range(QUERY_COUNT):
        pool_index = (index * POOL_COUNT) // QUERY_COUNT
        size = POOL_SIZES[pool_index % len(POOL_SIZES)]
        ordinal = index % size
        global_ordinal = offsets[pool_index] + ordinal
        row: dict[str, JsonValue] = {
            "category_code": f"PERF-CAT-{pool_index % 25:02d}",
            "detail_category_code": f"PERF-DETAIL-{pool_index:03d}",
            "page": 1,
            "page_size": 50,
            "product_name": f"영상감시장치-{pool_index:03d}",
            "query_id": f"QUERY-{index:03d}",
            "spec_text": (
                (
                    f"해상도 {2 + (global_ordinal % 15)}MP | "
                    f"{15 + (5 * (global_ordinal % 10))}fps | "
                    f"저장 {1 + (global_ordinal % 16)}TB | "
                    f"모델 PERF-{global_ordinal:05d}"
                )
                if index < SPEC_QUERY_COUNT
                else ""
            ),
        }
        if index < PRICE_QUERY_COUNT:
            price_source = _lowest_valid_price_ordinal(offsets[pool_index])
            target = 100_000 + ((price_source % 1_000) * 1_000)
            row.update(
                {
                    "price_tolerance_pct": "25.00",
                    "price_unit": "대",
                    "target_price_won": target,
                }
            )
        rows.append(row)
    return (canonical_json(rows) + "\n").encode()


def _lowest_valid_price_ordinal(pool_offset: int) -> int:
    global_ordinal = pool_offset
    while (
        global_ordinal % 10 == MISSING_PRICE_REMAINDER
        or global_ordinal % 20 == MIXED_UNIT_REMAINDER
    ):
        global_ordinal += 1
    return global_ordinal


def _write_manifest(path: Path, result: PerfCorpusResult) -> None:
    versions: dict[str, JsonValue] = {
        "numpy": version("numpy"),
        "python": platform.python_version(),
        "scikit-learn": version("scikit-learn"),
        "sqlite": sqlite3_version(),
    }
    environment: dict[str, JsonValue] = {
        key: os.environ[key] for key in THREAD_VARIABLES
    }
    manifest: dict[str, JsonValue] = {
        "artifacts": asdict(result),
        "created_at_utc": CREATED_AT,
        "environment": environment,
        "hardware": {
            "disk_free_bytes": shutil.disk_usage(path.parent).free,
            "disk_total_bytes": shutil.disk_usage(path.parent).total,
            "machine": platform.machine(),
            "platform": sys.platform,
            "processor": platform.processor() or platform.machine(),
            "ram_bytes": _ram_bytes(),
        },
        "request_mix": {
            "price": PRICE_QUERY_COUNT,
            "spec": SPEC_QUERY_COUNT,
            "total": QUERY_COUNT,
        },
        "schema_version": VERSION,
        "seed": SEED,
        "versions": versions,
    }
    _ = path.write_text(canonical_json(manifest) + "\n", encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ram_bytes() -> int:
    if sys.platform == "win32":
        return _windows_ram_bytes()
    page_size = os.sysconf("SC_PAGE_SIZE")
    physical_pages = os.sysconf("SC_PHYS_PAGES")
    return page_size * physical_pages


def _windows_ram_bytes() -> int:
    powershell = shutil.which("powershell")
    if powershell is None:
        return 0
    result = subprocess.run(  # noqa: S603 -- absolute system executable, fixed argv
        (
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[long](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())
