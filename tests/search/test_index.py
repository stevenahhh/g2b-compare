from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from g2b_compare.db.hashes import canonical_json
from g2b_compare.search.index_builder import (
    IndexBuildRequest,
    IndexBundle,
    build_index,
)
from g2b_compare.search.index_format import (
    EXACT_MEMBER_NAMES,
    IndexFormatError,
    artifact_sha256,
    validate_bundle,
)
from g2b_compare.search.index_store import IndexStore
from g2b_compare.search.models import IndexManifest, IndexSettings, ProductRow

from .support import corpus, product


class GoldenReceipt(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    artifact_sha256: str
    manifest_sha256: str
    word_features: tuple[str, ...]
    char_features: tuple[str, ...]
    members_sha256: dict[str, str]


ROWS_ADAPTER = TypeAdapter(tuple[ProductRow, ...])


def test_index_is_byte_deterministic_and_has_exact_members() -> None:
    # Given: one inactive materialization corpus in two input orders
    request = IndexBuildRequest(17, "v1", "v1", "v1", corpus())
    shuffled = IndexBuildRequest(17, "v1", "v1", "v1", tuple(reversed(corpus())))

    # When: both indices are built
    first = build_index(request)
    replay = build_index(shuffled)

    # Then: all bytes and identities are stable and exactly eight-membered
    assert first.member_names == EXACT_MEMBER_NAMES
    assert first.members == replay.members
    assert first.artifact_sha256 == replay.artifact_sha256
    assert first.manifest_sha256 == replay.manifest_sha256
    rows = ROWS_ADAPTER.validate_json(first.member("product-rows.json"))
    assert [(item.product_id, item.row) for item in rows] == [
        (product_id, row)
        for row, product_id in enumerate(("P-01", "P-02", "P-03", "P-04", "P-05"))
    ]


def test_empty_index_has_typed_zero_column_csr_bytes() -> None:
    # Given: active products whose option text is empty
    request = IndexBuildRequest(18, "v1", "v1", "v1", (product("E-1", option=""),))

    # When: the index is built
    bundle = build_index(request)

    # Then: it is a valid typed empty index retaining the document row
    validated = validate_bundle(bundle.members, bundle.manifest)
    assert validated.product_ids == ("E-1",)
    assert validated.word_shape == (1, 0)
    assert validated.char_shape == (1, 0)
    assert bundle.member("word-idf.f64le") == b""
    assert bundle.member("word-vocabulary.json") == b"{}"


def test_golden_index_hashes_are_exact() -> None:
    # Given: the fixed v1 corpus and committed independent receipt
    expected = GoldenReceipt.model_validate_json(
        Path("tests/fixtures/search/index-v1-golden.json").read_bytes()
    )

    # When: the same corpus is rebuilt
    bundle = build_index(IndexBuildRequest(17, "v1", "v1", "v1", corpus()))

    # Then: feature orders and byte hashes match the golden receipt
    settings = IndexSettings.model_validate_json(bundle.member("settings.json"))
    assert bundle.artifact_sha256 == expected.artifact_sha256
    assert bundle.manifest_sha256 == expected.manifest_sha256
    assert settings.word.features == expected.word_features
    assert settings.char.features == expected.char_features
    assert {
        name: hashlib.sha256(value).hexdigest() for name, value in bundle.members
    } == expected.members_sha256


def test_bad_index_version_is_typed() -> None:
    # Given: an unsupported index version
    request = IndexBuildRequest(17, "v1", "v1", "v2", corpus())

    # When/Then: the boundary rejects it before fitting
    with pytest.raises(IndexFormatError, match="bad-index-version"):
        _ = build_index(request)


def test_bundle_ownership_and_actual_member_derivations_are_strict(
    tmp_path: Path,
) -> None:
    products = corpus()
    request = IndexBuildRequest(17, "v1", "v1", "v1", products)
    foreign = build_index(IndexBuildRequest(18, "v1", "v1", "v1", products))
    store = IndexStore.create(tmp_path / "ownership.sqlite3")

    try:
        with pytest.raises(IndexFormatError, match="bundle-ownership-mismatch"):
            store.publish(request, foreign)
    finally:
        store.close()

    valid = build_index(request)
    settings = IndexSettings.model_validate_json(valid.member("settings.json"))
    mutations = (
        settings.model_copy(update={"materialization_id": 18}),
        settings.model_copy(
            update={
                "word": settings.word.model_copy(
                    update={"features": tuple(reversed(settings.word.features))}
                )
            }
        ),
        settings.model_copy(
            update={
                "word": settings.word.model_copy(update={"vocabulary_sha256": "0" * 64})
            }
        ),
        settings.model_copy(
            update={"word": settings.word.model_copy(update={"idf_sha256": "0" * 64})}
        ),
    )
    for mutation in mutations:
        false_bundle = _reframed_settings(valid, mutation)
        with pytest.raises(IndexFormatError, match="hash-framing"):
            _ = validate_bundle(false_bundle.members, false_bundle.manifest)


def _reframed_settings(bundle: IndexBundle, settings: IndexSettings) -> IndexBundle:
    settings_bytes = canonical_json(settings.model_dump(mode="json")).encode("utf-8")
    members = tuple(
        (name, settings_bytes if name == "settings.json" else value)
        for name, value in bundle.members
    )
    manifest = IndexManifest.model_validate_json(bundle.manifest).model_copy(
        update={
            "artifact_sha256": artifact_sha256(members),
            "member_sha256": {
                name: hashlib.sha256(value).hexdigest() for name, value in members
            },
        }
    )
    manifest_bytes = canonical_json(manifest.model_dump(mode="json")).encode("utf-8")
    return IndexBundle(
        members,
        manifest_bytes,
        manifest.artifact_sha256,
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
