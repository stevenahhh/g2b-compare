"""Atomic full-document estimate persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import SqlRow, as_text, query

from .estimate_drafts import read_draft
from .estimate_models import (
    EstimateDraft,
    EstimateLine,
    EstimateLineInput,
)
from .estimate_store_records import (
    document_line,
    insert_line,
    line_from_row,
    require_quantity,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocumentReplacement:
    """One validated latest-document write."""

    title: str
    template_sha256: str
    lines: tuple[tuple[str, EstimateLineInput], ...]


def refresh_comparisons(
    database: Path,
    estimate_id: str,
    comparison_seed: Callable[[sqlite3.Connection, tuple[EstimateLine, ...]], None],
) -> EstimateDraft:
    """Atomically replace one document's comparison snapshots."""
    with connect(database) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        draft = read_draft(connection, estimate_id)
        _ = query(
            connection,
            """
            DELETE FROM estimate_comparisons
            WHERE estimate_line_id IN (
                SELECT id FROM estimate_lines WHERE estimate_id = ?
            )
            """,
            (estimate_id,),
        )
        comparison_seed(connection, draft.lines)
        _ = connection.commit()
    return draft


def replace_draft(
    database: Path,
    estimate_id: str,
    replacement: DocumentReplacement,
    comparison_seed: Callable[[sqlite3.Connection, tuple[EstimateLine, ...]], None],
) -> EstimateDraft:
    """Atomically persist one latest full document without quantity merging."""
    title = replacement.title
    template_sha256 = replacement.template_sha256
    for _line_id, item in replacement.lines:
        require_quantity(item.quantity)
    now = datetime.now(UTC).isoformat()
    desired_lines = tuple(
        document_line(line_id, line_no, item)
        for line_no, (line_id, item) in enumerate(replacement.lines, start=1)
    )
    previous_comparisons: list[SqlRow] = []
    with connect(database) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        draft_row = query(
            connection,
            """
            SELECT id, title, template_sha256, created_at, updated_at
            FROM estimate_drafts WHERE id = ?
            """,
            (estimate_id,),
        ).fetchone()
        if draft_row is None:
            created_at = now
            _ = query(
                connection,
                "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
                (estimate_id, title, template_sha256, now, now),
            )
            previous_lines: tuple[EstimateLine, ...] = ()
        else:
            created_at = as_text(draft_row[3])
            previous_lines = tuple(
                line_from_row(row)
                for row in query(
                    connection,
                    """
                    SELECT id, line_no, line_kind, product_id,
                    parent_product_id, relation_id, offer_operation, offer_key,
                    item_name_snapshot, spec_snapshot, company_snapshot,
                    unit_snapshot, unit_price_won_snapshot, quantity
                    FROM estimate_lines WHERE estimate_id = ? ORDER BY line_no
                    """,
                    (estimate_id,),
                ).fetchall()
            )
            if as_text(draft_row[1]) == title and previous_lines == desired_lines:
                comparison_seed(connection, previous_lines)
                _ = connection.commit()
                return EstimateDraft(
                    estimate_id,
                    title,
                    as_text(draft_row[2]),
                    created_at,
                    as_text(draft_row[4]),
                    previous_lines,
                )
            previous_comparisons = query(
                connection,
                """
                SELECT comparison.estimate_line_id, comparison.slot,
                comparison.product_id, comparison.relation_id,
                comparison.company_snapshot, comparison.spec_snapshot,
                comparison.price_won_snapshot
                FROM estimate_comparisons AS comparison
                JOIN estimate_lines AS line
                ON line.id = comparison.estimate_line_id
                WHERE line.estimate_id = ?
                """,
                (estimate_id,),
            ).fetchall()

        _ = query(
            connection,
            "DELETE FROM estimate_lines WHERE estimate_id = ?",
            (estimate_id,),
        )
        for line in desired_lines:
            insert_line(connection, estimate_id, line)
        previous_by_id = {line.id: line for line in previous_lines}
        stable_ids = {
            line.id
            for line in desired_lines
            if (previous := previous_by_id.get(line.id)) is not None
            and _identity(previous) == _identity(line)
        }
        for comparison in previous_comparisons:
            if as_text(comparison[0]) in stable_ids:
                _ = query(
                    connection,
                    "INSERT INTO estimate_comparisons VALUES (?, ?, ?, ?, ?, ?, ?)",
                    comparison,
                )
        comparison_seed(connection, desired_lines)
        if draft_row is not None:
            _ = query(
                connection,
                """
                UPDATE estimate_drafts SET title = ?, template_sha256 = ?,
                updated_at = ? WHERE id = ?
                """,
                (title, template_sha256, now, estimate_id),
            )
        _ = connection.commit()
    return EstimateDraft(
        estimate_id,
        title,
        template_sha256,
        created_at,
        now,
        desired_lines,
    )


def _identity(line: EstimateLine) -> tuple[object, ...]:
    return (
        line.line_kind,
        line.product_id,
        line.parent_product_id,
        line.relation_id,
        line.offer_operation,
        line.offer_key,
        line.item_name_snapshot,
        line.spec_snapshot,
        line.company_snapshot,
        line.unit_snapshot,
        line.unit_price_won_snapshot,
    )
