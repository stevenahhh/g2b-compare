from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.search.capabilities import FTS5UnavailableError, require_fts5
from g2b_compare.search.index_builder import (
    IndexBuildRequest,
    IndexBundle,
    build_index,
)
from g2b_compare.search.index_format import (
    IndexFormatError,
    artifact_sha256,
    decode_csr1,
    validate_bundle,
)
from g2b_compare.search.index_store import IndexStore
from g2b_compare.search.models import IndexManifest
from g2b_compare.search.query import (
    DB_WRITE_AT_SEARCH,
    NETWORK_AT_SEARCH,
    IndexMembershipError,
    SearchPurityError,
)

from .heavy_support import purity_contract_failure, run_heavy_evidence
from .support import corpus, product

if TYPE_CHECKING:
    from collections.abc import Callable

SCENARIOS: Final = (
    "wrong-category",
    "no-detail-expansion",
    "fts5-disabled",
    "bad-index-version",
    "empty-db",
    "network-at-search",
    "db-write-at-search",
    "csr-unsorted-index",
    "csr-duplicate-feature",
    "csr-negative-zero",
    "empty-index-bytes",
    "member-missing",
    "member-extra",
    "json-newline",
    "hash-framing",
    "manifest-circularity",
)


@dataclass(frozen=True, slots=True)
class HappyResult:
    members: int
    exact_ids: tuple[str, ...]
    active_release_unchanged: bool
    release_graph_preserved_on_success: bool
    release_graph_preserved_on_failure: bool
    query_paths_pure: bool


@dataclass(frozen=True, slots=True)
class FailureObservation:
    assertion_class: str
    message: str


def run_happy() -> HappyResult:
    receipt = run_heavy_evidence()
    return HappyResult(
        receipt.members,
        receipt.exact_ids,
        receipt.success_preserved and receipt.failure_preserved,
        receipt.success_preserved,
        receipt.failure_preserved,
        receipt.query_paths_pure,
    )


def observe_failure(scenario: str) -> FailureObservation:
    try:
        _run_failure(scenario)
    except (
        FTS5UnavailableError,
        IndexFormatError,
        IndexMembershipError,
        SearchPurityError,
    ) as error:
        return FailureObservation(type(error).__name__, str(error))
    return FailureObservation("MissingFailure", scenario)


def _run_failure(scenario: str) -> None:
    SCENARIO_RUNNERS[scenario]()


def _membership_failure(category: tuple[str, str]) -> None:
    with TemporaryDirectory() as directory:
        store = IndexStore.create(Path(directory) / "membership.sqlite3")
        request = IndexBuildRequest(17, "v1", "v1", "v1", corpus())
        store.publish(request, build_index(request))
        try:
            _ = store.resolve_exact("영상감시장치", category)
        finally:
            store.close()


def _bundle() -> IndexBundle:
    return build_index(IndexBuildRequest(17, "v1", "v1", "v1", corpus()))


def _validate_replaced(
    bundle: IndexBundle, name: str, value: bytes, *, reframe: bool = True
) -> None:
    members = tuple(
        (member, value if member == name else raw)
        for member, raw in bundle.members
    )
    manifest = bundle.manifest
    if reframe:
        parsed = IndexManifest.model_validate_json(manifest)
        raw_manifest = _manifest_value(parsed)
        raw_manifest["artifact_sha256"] = artifact_sha256(members)
        raw_manifest["member_sha256"] = {
            member: hashlib.sha256(raw).hexdigest()
            for member, raw in members
        }
        manifest = canonical_json(raw_manifest).encode("utf-8")
    _ = validate_bundle(members, manifest)


def _csr_failure(scenario: str) -> None:
    bundle = _bundle()
    decoded = decode_csr1(bundle.member("word-matrix.csr1"))
    indices = list(decoded.indices)
    data = list(decoded.data)
    start = next(
        decoded.indptr[row]
        for row in range(decoded.rows)
        if decoded.indptr[row + 1] - decoded.indptr[row] >= 2
    )
    if scenario == "csr-unsorted-index":
        indices[start], indices[start + 1] = indices[start + 1], indices[start]
    elif scenario == "csr-duplicate-feature":
        indices[start + 1] = indices[start]
    else:
        data[0] = -0.0
    payload = b"".join(
        (
            b"CSR1",
            struct.pack(
                "<QQQQ",
                decoded.rows,
                decoded.cols,
                len(data),
                len(decoded.indptr),
            ),
            struct.pack(f"<{len(decoded.indptr)}q", *decoded.indptr),
            struct.pack(f"<{len(indices)}i", *indices),
            struct.pack(f"<{len(data)}d", *data),
        )
    )
    _validate_replaced(bundle, "word-matrix.csr1", payload)


def _bad_version() -> None:
    _ = build_index(IndexBuildRequest(17, "v1", "v1", "v2", corpus()))


def _empty_database() -> None:
    with TemporaryDirectory() as directory:
        store = IndexStore.create(Path(directory) / "empty.sqlite3")
        try:
            _ = store.resolve_exact("영상감시장치")
        finally:
            store.close()


def _empty_index_bytes() -> None:
    bundle = build_index(
        IndexBuildRequest(18, "v1", "v1", "v1", (product("E", option=""),))
    )
    _validate_replaced(bundle, "word-matrix.csr1", b"CSR1")


def _member_missing() -> None:
    bundle = _bundle()
    _ = validate_bundle(bundle.members[:-1], bundle.manifest)


def _member_extra() -> None:
    bundle = _bundle()
    _ = validate_bundle((*bundle.members, ("z-extra", b"")), bundle.manifest)


def _json_corruption(suffix: bytes, *, reframe: bool) -> None:
    bundle = _bundle()
    value = bundle.member("settings.json") + suffix
    _validate_replaced(bundle, "settings.json", value, reframe=reframe)


def _manifest_circularity() -> None:
    bundle = _bundle()
    parsed = IndexManifest.model_validate_json(bundle.manifest)
    manifest = _manifest_value(parsed)
    manifest["manifest_sha256"] = "0" * 64
    _ = validate_bundle(bundle.members, canonical_json(manifest).encode("utf-8"))


def _manifest_value(manifest: IndexManifest) -> dict[str, JsonValue]:
    return {
        "artifact_sha256": manifest.artifact_sha256,
        "index_version": manifest.index_version,
        "materialization_id": manifest.materialization_id,
        "member_sha256": dict(manifest.member_sha256),
        "normalization_version": manifest.normalization_version,
        "tokenizer_version": manifest.tokenizer_version,
    }


SCENARIO_RUNNERS: Final[dict[str, Callable[[], None]]] = {
    "wrong-category": partial(_membership_failure, ("9999", "999999")),
    "no-detail-expansion": partial(_membership_failure, ("4410", "999999")),
    "fts5-disabled": partial(require_fts5, available=False),
    "bad-index-version": _bad_version,
    "empty-db": _empty_database,
    "network-at-search": partial(purity_contract_failure, NETWORK_AT_SEARCH),
    "db-write-at-search": partial(purity_contract_failure, DB_WRITE_AT_SEARCH),
    "csr-unsorted-index": partial(_csr_failure, "csr-unsorted-index"),
    "csr-duplicate-feature": partial(_csr_failure, "csr-duplicate-feature"),
    "csr-negative-zero": partial(_csr_failure, "csr-negative-zero"),
    "empty-index-bytes": _empty_index_bytes,
    "member-missing": _member_missing,
    "member-extra": _member_extra,
    "json-newline": partial(_json_corruption, b"\n", reframe=True),
    "hash-framing": partial(_json_corruption, b" ", reframe=False),
    "manifest-circularity": _manifest_circularity,
}
