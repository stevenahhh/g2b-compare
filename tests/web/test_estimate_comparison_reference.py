"""Workbook-grounded comparison reference contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.priority_store import PriorityStore
from g2b_compare.services import EstimateLineInput, EstimateStore
from g2b_compare.web.estimate_comparison_reference import (
    comparison_reference_documents,
)
from g2b_compare.web.estimate_selection import (
    comparison_views,
    seed_document_comparisons_in_transaction,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_reference_catalog_contains_both_complete_workbooks() -> None:
    documents = comparison_reference_documents()

    assert [len(document.rows) for document in documents] == [9, 24]
    assert sum(len(document.rows) for document in documents) == 33
    assert (
        len(
            {
                (
                    row.comparisons[0].product_id,
                    row.quantity,
                )
                for document in documents
                for row in document.rows
            }
        )
        == 33
    )


def test_matching_reference_document_seeds_exact_comparisons(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _ = PriorityStore(database)
    migrate(database)
    document = comparison_reference_documents()[0]
    store = EstimateStore(database)
    expected_by_line: dict[
        str,
        tuple[tuple[str, str, str, int], ...],
    ] = {}
    inputs: list[tuple[str, EstimateLineInput]] = []
    for index, row in enumerate(document.rows, start=1):
        line_id = f"{index:032x}"
        selected = row.comparisons[0]
        inputs.append(
            (
                line_id,
                EstimateLineInput(
                    "main",
                    selected.product_id,
                    None,
                    None,
                    None,
                    None,
                    "workbook reference",
                    selected.spec,
                    selected.company,
                    "식",
                    selected.price_won,
                    Decimal(row.quantity),
                ),
            )
        )
        expected_by_line[line_id] = tuple(
            (
                comparison.product_id,
                comparison.company,
                comparison.spec,
                comparison.price_won,
            )
            for comparison in row.comparisons
        )

    draft = store.replace_draft(
        "f" * 32,
        "workbook reference",
        "0" * 64,
        tuple(inputs),
        seed_document_comparisons_in_transaction,
    )
    actual = comparison_views(database, draft)

    assert {
        line_id: tuple(
            (
                comparison.product_id,
                comparison.company,
                comparison.spec,
                comparison.price_won,
            )
            for comparison in comparisons
        )
        for line_id, comparisons in actual.items()
    } == expected_by_line

    first_line_id = draft.lines[0].id
    with connect(database) as connection:
        _ = connection.execute(
            """
            UPDATE estimate_comparisons
            SET product_id = CASE slot
                    WHEN 'B' THEN '99999998'
                    ELSE '99999997'
                END,
                company_snapshot = slot || '-stale'
            WHERE estimate_line_id = ? AND slot IN ('B', 'C')
            """,
            (first_line_id,),
        )
        seed_document_comparisons_in_transaction(connection, draft.lines)

    refreshed = comparison_views(database, draft)
    assert (
        tuple(
            (
                comparison.product_id,
                comparison.company,
                comparison.spec,
                comparison.price_won,
            )
            for comparison in refreshed[first_line_id]
        )
        == expected_by_line[first_line_id]
    )


def test_matching_reference_subset_seeds_missing_local_products(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _ = PriorityStore(database)
    migrate(database)
    reference = comparison_reference_documents()[1].rows[14]
    selected = reference.comparisons[0]
    line_id = "e" * 32
    store = EstimateStore(database)

    draft = store.replace_draft(
        "d" * 32,
        "workbook subset",
        "0" * 64,
        (
            (
                line_id,
                EstimateLineInput(
                    "main",
                    selected.product_id,
                    None,
                    None,
                    None,
                    None,
                    "workbook reference",
                    selected.spec,
                    selected.company,
                    "식",
                    selected.price_won,
                    Decimal(reference.quantity),
                ),
            ),
        ),
        seed_document_comparisons_in_transaction,
    )

    assert [
        comparison.product_id
        for comparison in comparison_views(database, draft)[line_id]
    ] == [comparison.product_id for comparison in reference.comparisons]
