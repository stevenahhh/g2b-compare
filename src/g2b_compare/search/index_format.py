"""Serialize and strictly validate the v1 eight-member index format."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, override

import numpy as np
from pydantic import TypeAdapter, ValidationError

from .integrity import IndexIdentity, derive_integrity_identity
from .jcs import JcsInputs, jcs_members_valid
from .models import IndexManifest, IndexSettings, ProductRow

EXACT_MEMBER_NAMES: Final = (
    "char-idf.f64le",
    "char-matrix.csr1",
    "char-vocabulary.json",
    "product-rows.json",
    "settings.json",
    "word-idf.f64le",
    "word-matrix.csr1",
    "word-vocabulary.json",
)
ROWS_ADAPTER: Final = TypeAdapter(tuple[ProductRow, ...])
VOCABULARY_ADAPTER: Final = TypeAdapter(dict[str, int])
INTS_ADAPTER: Final = TypeAdapter(tuple[int, ...])
FLOATS_ADAPTER: Final = TypeAdapter(tuple[float, ...])
CSR_HEADER_SIZE: Final = 36
BAD_INDEX_VERSION: Final = "bad-index-version"
CSR_DUPLICATE_FEATURE: Final = "csr-duplicate-feature"
CSR_NEGATIVE_ZERO: Final = "csr-negative-zero"
CSR_UNSORTED_INDEX: Final = "csr-unsorted-index"
EMPTY_INDEX_BYTES: Final = "empty-index-bytes"
HASH_FRAMING: Final = "hash-framing"
JSON_NEWLINE: Final = "json-newline"
MANIFEST_CIRCULARITY: Final = "manifest-circularity"
MEMBER_EXTRA: Final = "member-extra"
MEMBER_MISSING: Final = "member-missing"


class IndexFormatError(Exception):
    """Reject one malformed or version-incompatible index boundary."""

    detail: str

    def __init__(self, detail: str) -> None:
        """Initialize one stable failure identifier."""
        super().__init__(detail)
        self.detail = detail

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class DecodedCSR:
    """Validated canonical CSR1 arrays without platform-native byte order."""

    rows: int
    cols: int
    indptr: tuple[int, ...]
    indices: tuple[int, ...]
    data: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ValidatedIndex:
    """Trusted index identities and shapes returned by bundle parsing."""

    product_ids: tuple[str, ...]
    word_shape: tuple[int, int]
    char_shape: tuple[int, int]
    identity: IndexIdentity


def frame_members(members: tuple[tuple[str, bytes], ...]) -> bytes:
    """Frame members with fixed little-endian name and byte lengths."""
    framed = bytearray()
    for name, value in sorted(members, key=lambda item: item[0].encode("ascii")):
        name_bytes = name.encode("ascii")
        framed.extend(struct.pack("<I", len(name_bytes)))
        framed.extend(name_bytes)
        framed.extend(struct.pack("<Q", len(value)))
        framed.extend(value)
    return bytes(framed)


def artifact_sha256(members: tuple[tuple[str, bytes], ...]) -> str:
    """Hash exactly the framed data members and never the manifest."""
    return hashlib.sha256(frame_members(members)).hexdigest()


def serialize_csr1(
    rows: int,
    cols: int,
    indptr: tuple[int, ...],
    indices: tuple[int, ...],
    data: tuple[float, ...],
) -> bytes:
    """Serialize canonical CSR arrays after applying the reader's invariants."""
    payload = b"".join(
        (
            b"CSR1",
            struct.pack("<QQQQ", rows, cols, len(data), len(indptr)),
            struct.pack(f"<{len(indptr)}q", *indptr),
            struct.pack(f"<{len(indices)}i", *indices),
            struct.pack(f"<{len(data)}d", *data),
        )
    )
    _ = decode_csr1(payload)
    return payload


def decode_csr1(payload: bytes) -> DecodedCSR:
    """Parse CSR1 while rejecting ambiguous sparse encodings."""
    if len(payload) < CSR_HEADER_SIZE or payload[:4] != b"CSR1":
        raise IndexFormatError(EMPTY_INDEX_BYTES)
    rows = _read_u64(payload, 4)
    cols = _read_u64(payload, 12)
    nnz = _read_u64(payload, 20)
    indptr_len = _read_u64(payload, 28)
    expected = CSR_HEADER_SIZE + indptr_len * 8 + nnz * 4 + nnz * 8
    if len(payload) != expected or indptr_len != rows + 1:
        raise IndexFormatError(EMPTY_INDEX_BYTES)
    offset = CSR_HEADER_SIZE
    indptr = INTS_ADAPTER.validate_python(
        np.frombuffer(payload, dtype="<i8", count=indptr_len, offset=offset).tolist()
    )
    offset += indptr_len * 8
    indices = INTS_ADAPTER.validate_python(
        np.frombuffer(payload, dtype="<i4", count=nnz, offset=offset).tolist()
    )
    offset += nnz * 4
    data = FLOATS_ADAPTER.validate_python(
        np.frombuffer(payload, dtype="<f8", count=nnz, offset=offset).tolist()
    )
    if not indptr or indptr[0] != 0 or indptr[-1] != nnz:
        raise IndexFormatError(EMPTY_INDEX_BYTES)
    if any(left > right for left, right in pairwise(indptr)):
        raise IndexFormatError(EMPTY_INDEX_BYTES)
    _validate_rows(cols, indptr, indices)
    for value in data:
        if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
            raise IndexFormatError(CSR_NEGATIVE_ZERO)
        if value == 0.0:
            raise IndexFormatError(EMPTY_INDEX_BYTES)
    return DecodedCSR(rows, cols, indptr, indices, data)


def _read_u64(payload: bytes, offset: int) -> int:
    return int.from_bytes(payload[offset : offset + 8], "little", signed=False)


def _validate_rows(
    cols: int, indptr: tuple[int, ...], indices: tuple[int, ...]
) -> None:
    for row in range(len(indptr) - 1):
        values = indices[indptr[row] : indptr[row + 1]]
        if any(value < 0 or value >= cols for value in values):
            raise IndexFormatError(CSR_UNSORTED_INDEX)
        for left, right in pairwise(values):
            if left == right:
                raise IndexFormatError(CSR_DUPLICATE_FEATURE)
            if left > right:
                raise IndexFormatError(CSR_UNSORTED_INDEX)


def validate_bundle(
    members: tuple[tuple[str, bytes], ...], manifest: bytes
) -> ValidatedIndex:
    """Validate exact membership, JCS bytes, hashes, versions, and CSR shapes."""
    member_map = _validate_members(members)
    for name in (
        "char-vocabulary.json",
        "product-rows.json",
        "settings.json",
        "word-vocabulary.json",
    ):
        _validate_json_bytes(member_map[name])
    _validate_json_bytes(manifest)
    if b"manifest.json" in manifest or b"manifest_sha" in manifest:
        raise IndexFormatError(MANIFEST_CIRCULARITY)
    try:
        parsed_manifest = IndexManifest.model_validate_json(manifest)
        settings = IndexSettings.model_validate_json(member_map["settings.json"])
        rows = ROWS_ADAPTER.validate_json(member_map["product-rows.json"])
        word_vocab = VOCABULARY_ADAPTER.validate_json(
            member_map["word-vocabulary.json"]
        )
        char_vocab = VOCABULARY_ADAPTER.validate_json(
            member_map["char-vocabulary.json"]
        )
    except ValidationError as error:
        raise IndexFormatError(HASH_FRAMING) from error
    if not jcs_members_valid(
        JcsInputs(
            member_map,
            manifest,
            parsed_manifest,
            settings,
            rows,
            word_vocab,
            char_vocab,
        )
    ):
        raise IndexFormatError(HASH_FRAMING)
    calculated = artifact_sha256(members)
    expected_hashes = {
        name: hashlib.sha256(value).hexdigest() for name, value in members
    }
    if parsed_manifest.artifact_sha256 != calculated:
        raise IndexFormatError(HASH_FRAMING)
    if parsed_manifest.member_sha256 != expected_hashes:
        raise IndexFormatError(HASH_FRAMING)
    if settings.index_version != "v1" or parsed_manifest.index_version != "v1":
        raise IndexFormatError(BAD_INDEX_VERSION)
    identity = derive_integrity_identity(
        parsed_manifest,
        settings,
        member_map,
        word_vocab,
        char_vocab,
    )
    if identity is None:
        raise IndexFormatError(HASH_FRAMING)
    word = decode_csr1(member_map["word-matrix.csr1"])
    char = decode_csr1(member_map["char-matrix.csr1"])
    _validate_dimensions(
        rows,
        (word, char),
        (word_vocab, char_vocab),
        member_map,
    )
    return ValidatedIndex(
        tuple(row.product_id for row in rows),
        (word.rows, word.cols),
        (char.rows, char.cols),
        identity,
    )


def _validate_members(members: tuple[tuple[str, bytes], ...]) -> dict[str, bytes]:
    names = tuple(name for name, _value in members)
    if len(names) < len(EXACT_MEMBER_NAMES):
        raise IndexFormatError(MEMBER_MISSING)
    if len(names) > len(EXACT_MEMBER_NAMES):
        raise IndexFormatError(MEMBER_EXTRA)
    if names != EXACT_MEMBER_NAMES:
        raise IndexFormatError(MEMBER_MISSING)
    return dict(members)


def _validate_dimensions(
    rows: tuple[ProductRow, ...],
    matrices: tuple[DecodedCSR, DecodedCSR],
    vocabularies: tuple[dict[str, int], dict[str, int]],
    members: dict[str, bytes],
) -> None:
    word, char = matrices
    word_vocab, char_vocab = vocabularies
    if tuple(row.row for row in rows) != tuple(range(len(rows))):
        raise IndexFormatError(HASH_FRAMING)
    if word.rows != len(rows) or char.rows != len(rows):
        raise IndexFormatError(HASH_FRAMING)
    if word.cols != len(word_vocab) or char.cols != len(char_vocab):
        raise IndexFormatError(HASH_FRAMING)
    if len(members["word-idf.f64le"]) != word.cols * 8:
        raise IndexFormatError(HASH_FRAMING)
    if len(members["char-idf.f64le"]) != char.cols * 8:
        raise IndexFormatError(HASH_FRAMING)
    for vocabulary in (word_vocab, char_vocab):
        features = sorted(vocabulary, key=lambda value: value.encode("utf-8"))
        if vocabulary != {feature: index for index, feature in enumerate(features)}:
            raise IndexFormatError(HASH_FRAMING)


def _validate_json_bytes(payload: bytes) -> None:
    if payload.endswith((b"\n", b"\r")):
        raise IndexFormatError(JSON_NEWLINE)
