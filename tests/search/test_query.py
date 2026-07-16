from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from g2b_compare.search.capabilities import FTS5UnavailableError
from g2b_compare.search.index_builder import IndexBuildRequest, build_index
from g2b_compare.search.index_store import IndexStore

from .support import corpus

if TYPE_CHECKING:
    from pathlib import Path


def _store(path: Path) -> IndexStore:
    store = IndexStore.create(path)
    products = corpus()
    store.publish(
        IndexBuildRequest(17, "v1", "v1", "v1", products),
        build_index(IndexBuildRequest(17, "v1", "v1", "v1", products)),
    )
    return store


def test_exact_membership_never_expands_category_or_detail(tmp_path: Path) -> None:
    # Given: one exact name occurring in two category tuples
    store = _store(tmp_path / "search.sqlite3")

    # When: exact membership is resolved with and without category
    grouped = store.resolve_exact("영상감시장치")
    selected = store.resolve_exact("영상감시장치", ("4410", "441015"))

    # Then: omission groups exact tuples and selection never detail-expands
    assert tuple(group.category_key for group in grouped) == (
        ("4410", "441015"),
        ("4410", "441016"),
    )
    assert tuple(item.product_id for item in selected[0].products) == (
        "P-01",
        "P-02",
        "P-03",
    )


def test_fts_recall_and_tfidf_score_do_not_define_membership(tmp_path: Path) -> None:
    # Given: an initialized searchable index
    store = _store(tmp_path / "search.sqlite3")

    # When: autocomplete/recall and scoring are used
    recalled = store.recall("감시")
    scored = store.score("800만화소 실외형")

    # Then: recall may find names while scoring only orders global active rows
    assert tuple(item.product_id for item in recalled) == ("P-05",)
    assert scored[0].product_id == "P-01"
    assert scored[0].score > 0
    assert store.total_changes == 0


def test_startup_requires_fts5(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a runtime whose compile options explicitly lack FTS5
    monkeypatch.setattr(IndexStore, "fts5_available", staticmethod(lambda: False))

    # When/Then: startup fails with a diagnostic typed error
    with pytest.raises(FTS5UnavailableError, match="fts5-disabled"):
        _ = IndexStore.create(tmp_path / "disabled.sqlite3")
