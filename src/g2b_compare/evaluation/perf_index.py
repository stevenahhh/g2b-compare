"""Publish and load the production word/character TF-IDF perf index."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from pydantic import ValidationError

from g2b_compare.search.index_builder import (
    IndexBuildRequest,
    IndexBundle,
    build_index,
)
from g2b_compare.search.index_format import (
    EXACT_MEMBER_NAMES,
    ROWS_ADAPTER,
    IndexFormatError,
    artifact_sha256,
    frame_members,
    validate_bundle,
)
from g2b_compare.search.models import IndexManifest

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.search.models import IndexProduct

MAGIC: Final = b"PERFIDX1"
MATERIALIZATION_ID: Final = 1
NORMALIZATION_VERSION: Final = "normalization-v1"
TOKENIZER_VERSION: Final = "v1"
INDEX_VERSION: Final = "v1"
MALFORMED_INDEX: Final = "perf-index-malformed"


@dataclass(frozen=True, slots=True)
class PerfIndexReceipt:
    """Exact file, manifest, word/char matrix, and IDF hashes."""

    file_sha256: str
    manifest_sha256: str
    word_index_sha256: str
    char_index_sha256: str
    word_idf_sha256: str
    char_idf_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedPerfIndex:
    """Validated membership consumed by the performance search reader."""

    product_ids: tuple[str, ...]
    file_sha256: str


@dataclass(frozen=True, slots=True)
class PerfIndexError(Exception):
    """Reject an incomplete, corrupt, or noncanonical perf index container."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def write_perf_index(
    path: Path,
    products: tuple[IndexProduct, ...],
) -> PerfIndexReceipt:
    """Fit the production index and publish one deterministic binary container."""
    bundle = build_index(
        IndexBuildRequest(
            MATERIALIZATION_ID,
            NORMALIZATION_VERSION,
            TOKENIZER_VERSION,
            INDEX_VERSION,
            products,
        )
    )
    payload = (
        MAGIC
        + len(bundle.manifest).to_bytes(8, "little", signed=False)
        + bundle.manifest
        + frame_members(bundle.members)
    )
    _ = path.write_bytes(payload)
    loaded = load_perf_index(path)
    if loaded.product_ids != tuple(product.product_id for product in products):
        raise PerfIndexError(MALFORMED_INDEX)
    members = dict(bundle.members)
    return PerfIndexReceipt(
        loaded.file_sha256,
        bundle.manifest_sha256,
        _sha_bytes(members["word-matrix.csr1"]),
        _sha_bytes(members["char-matrix.csr1"]),
        _sha_bytes(members["word-idf.f64le"]),
        _sha_bytes(members["char-idf.f64le"]),
    )


def load_perf_index(path: Path) -> LoadedPerfIndex:
    """Parse the container and validate the complete production IndexBundle."""
    try:
        payload = path.read_bytes()
    except OSError:
        raise PerfIndexError(MALFORMED_INDEX) from None
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 8:
        raise PerfIndexError(MALFORMED_INDEX)
    manifest_size = int.from_bytes(
        payload[len(MAGIC) : len(MAGIC) + 8],
        "little",
        signed=False,
    )
    manifest_start = len(MAGIC) + 8
    manifest_end = manifest_start + manifest_size
    if manifest_end > len(payload):
        raise PerfIndexError(MALFORMED_INDEX)
    manifest = payload[manifest_start:manifest_end]
    members = _unframe(payload[manifest_end:])
    bundle = IndexBundle(
        members,
        manifest,
        artifact_sha256(members),
        _sha_bytes(manifest),
    )
    try:
        validated = validate_bundle(bundle.members, bundle.manifest)
    except IndexFormatError:
        raise PerfIndexError(MALFORMED_INDEX) from None
    return LoadedPerfIndex(validated.product_ids, _sha_bytes(payload))


def load_pinned_perf_index(path: Path, expected_sha256: str) -> LoadedPerfIndex:
    """Load pinned membership without decoding immutable sparse matrices."""
    try:
        payload = path.read_bytes()
    except OSError:
        raise PerfIndexError(MALFORMED_INDEX) from None
    digest = _sha_bytes(payload)
    if digest != expected_sha256:
        raise PerfIndexError(MALFORMED_INDEX)
    manifest, members = _selected_members(payload, frozenset(("product-rows.json",)))
    try:
        _ = IndexManifest.model_validate_json(manifest)
        rows = ROWS_ADAPTER.validate_json(members["product-rows.json"])
    except (KeyError, ValidationError):
        raise PerfIndexError(MALFORMED_INDEX) from None
    return LoadedPerfIndex(tuple(row.product_id for row in rows), digest)


def _unframe(payload: bytes) -> tuple[tuple[str, bytes], ...]:
    members: list[tuple[str, bytes]] = []
    offset = 0
    for expected in EXACT_MEMBER_NAMES:
        name_size, offset = _read_size(payload, offset, 4)
        name_end = offset + name_size
        expected_bytes = expected.encode("ascii")
        if name_end > len(payload) or payload[offset:name_end] != expected_bytes:
            raise PerfIndexError(MALFORMED_INDEX)
        value_size, value_start = _read_size(payload, name_end, 8)
        value_end = value_start + value_size
        if value_end > len(payload):
            raise PerfIndexError(MALFORMED_INDEX)
        members.append((expected, payload[value_start:value_end]))
        offset = value_end
    if offset != len(payload):
        raise PerfIndexError(MALFORMED_INDEX)
    return tuple(members)


def _selected_members(
    payload: bytes,
    selected: frozenset[str],
) -> tuple[bytes, dict[str, bytes]]:
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 8:
        raise PerfIndexError(MALFORMED_INDEX)
    manifest_size = int.from_bytes(
        payload[len(MAGIC) : len(MAGIC) + 8], "little", signed=False
    )
    offset = len(MAGIC) + 8
    manifest_end = offset + manifest_size
    if manifest_end > len(payload):
        raise PerfIndexError(MALFORMED_INDEX)
    manifest = payload[offset:manifest_end]
    offset = manifest_end
    values: dict[str, bytes] = {}
    for expected in EXACT_MEMBER_NAMES:
        name_size, offset = _read_size(payload, offset, 4)
        name_end = offset + name_size
        if name_end > len(payload) or payload[offset:name_end] != expected.encode(
            "ascii"
        ):
            raise PerfIndexError(MALFORMED_INDEX)
        value_size, value_start = _read_size(payload, name_end, 8)
        value_end = value_start + value_size
        if value_end > len(payload):
            raise PerfIndexError(MALFORMED_INDEX)
        if expected in selected:
            values[expected] = payload[value_start:value_end]
        offset = value_end
    if offset != len(payload):
        raise PerfIndexError(MALFORMED_INDEX)
    return manifest, values


def _read_size(payload: bytes, offset: int, width: int) -> tuple[int, int]:
    end = offset + width
    if end > len(payload):
        raise PerfIndexError(MALFORMED_INDEX)
    return int.from_bytes(payload[offset:end], "little", signed=False), end


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
