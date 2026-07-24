"""Pinned curated workbook relation import contracts."""

import hashlib
from pathlib import Path

from g2b_compare.importers.workbook_relations import (
    PINNED_SOURCE_SHA256,
    import_workbook_relations,
)

DATASET = Path("dataset")
PINNED_WORKBOOK = DATASET / (
    "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx"
)
OTHER_WORKBOOKS = (
    DATASET / "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx",
    DATASET
    / "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_imports_exact_curated_relations_and_unbound_options_read_only() -> None:
    # Given
    before = _sha256(PINNED_WORKBOOK)

    # When
    result = import_workbook_relations(PINNED_WORKBOOK)

    # Then
    assert before == PINNED_SOURCE_SHA256 == _sha256(PINNED_WORKBOOK)
    assert result.snapshot is not None
    assert result.snapshot.status == "complete"
    assert len(result.snapshot.source_manifest_sha) == 64
    assert len(result.snapshot.relation_content_sha) == 64
    assert len(result.relations) == 12
    assert len({relation.relation_id for relation in result.relations}) == 12
    assert {relation.parent_id for relation in result.relations} == {"24684676"}
    rows = tuple(relation.row_no for relation in result.relations)
    assert rows == tuple(range(11, 23))
    assert all(
        relation.source_sha == PINNED_SOURCE_SHA256 for relation in result.relations
    )
    assert all(relation.sheet_name == "자재내역서" for relation in result.relations)
    assert len(result.quarantined) == 3
    assert tuple(item.row_no for item in result.quarantined) == (27, 28, 29)
    assert all(item.reason == "unbound_option" for item in result.quarantined)


def test_other_workbooks_and_comparison_columns_import_zero_relations() -> None:
    # Given
    before = tuple(_sha256(path) for path in OTHER_WORKBOOKS)

    # When
    results = tuple(import_workbook_relations(path) for path in OTHER_WORKBOOKS)

    # Then
    assert all(result.snapshot is None for result in results)
    assert all(result.relations == () for result in results)
    assert all(result.quarantined == () for result in results)
    assert before == tuple(_sha256(path) for path in OTHER_WORKBOOKS)
