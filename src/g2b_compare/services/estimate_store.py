"""Persist immutable estimate snapshots in the local SQLite database."""
# noqa: SIZE_OK - Legacy CRUD and the transactional document path share one store.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal, final
from uuid import uuid4

from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import SqlRow, SqlValue, as_int, as_text, query

from .estimate_models import (
    EstimateDraft,
    EstimateFullError,
    EstimateLine,
    EstimateLineInput,
    EstimateNotFoundError,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

MAX_ESTIMATE_LINES: Final = 9


@final
class EstimateStore:
    """Transactional owner for estimate drafts and snapshots."""

    def __init__(self, database: Path) -> None:
        """Open the store over one migrated application database."""
        self.database = database
        migrate(database)

    def create_draft(self, title: str, template_sha256: str) -> EstimateDraft:
        """Create one empty draft pinned to a template version."""
        estimate_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        with connect(self.database) as connection:
            _ = query(
                connection,
                "INSERT INTO estimate_drafts VALUES (?, ?, ?, ?, ?)",
                (estimate_id, title, template_sha256, now, now),
            )
        return EstimateDraft(estimate_id, title, template_sha256, now, now, ())

    def draft_count(self) -> int:
        """Return the number used for the next visible draft sequence."""
        with connect(self.database) as connection:
            row = query(connection, "SELECT COUNT(*) FROM estimate_drafts").fetchone()
        return 0 if row is None else as_int(row[0])

    def get_draft(self, estimate_id: str) -> EstimateDraft:
        """Return one draft and its current ordered snapshots."""
        with connect(self.database) as connection:
            row = query(
                connection,
                """
                SELECT id, title, template_sha256, created_at, updated_at
                FROM estimate_drafts WHERE id = ?
                """,
                (estimate_id,),
            ).fetchone()
            if row is None:
                raise EstimateNotFoundError(estimate_id)
            line_rows = query(
                connection,
                """
                SELECT id, line_no, line_kind, product_id, parent_product_id,
                relation_id, offer_operation, offer_key, item_name_snapshot,
                spec_snapshot, company_snapshot, unit_snapshot,
                unit_price_won_snapshot, quantity FROM estimate_lines
                WHERE estimate_id = ? ORDER BY line_no
                """,
                (estimate_id,),
            ).fetchall()
        return EstimateDraft(
            id=as_text(row[0]),
            title=as_text(row[1]),
            template_sha256=as_text(row[2]),
            created_at=as_text(row[3]),
            updated_at=as_text(row[4]),
            lines=tuple(_line(item) for item in line_rows),
        )

    def add_line(self, estimate_id: str, item: EstimateLineInput) -> EstimateLine:
        """Append a snapshot or merge an identical verified option relation."""
        _require_quantity(item.quantity)
        with connect(self.database) as connection:
            _ = connection.execute("BEGIN IMMEDIATE")
            _require_draft(connection, estimate_id)
            if item.relation_id is not None:
                existing = query(
                    connection,
                    """
                    SELECT id, quantity FROM estimate_lines
                    WHERE estimate_id = ? AND relation_id = ?
                    """,
                    (estimate_id, item.relation_id),
                ).fetchone()
                if existing is not None:
                    line_id = as_text(existing[0])
                    quantity = Decimal(str(existing[1])) + item.quantity
                    _ = query(
                        connection,
                        "UPDATE estimate_lines SET quantity = ? WHERE id = ?",
                        (str(quantity), line_id),
                    )
                    _touch(connection, estimate_id)
                    line = _read_line(connection, line_id)
                    _ = connection.commit()
                    return line
            count_row = query(
                connection,
                "SELECT COUNT(*) FROM estimate_lines WHERE estimate_id = ?",
                (estimate_id,),
            ).fetchone()
            if count_row is None or as_int(count_row[0]) >= MAX_ESTIMATE_LINES:
                raise EstimateFullError(estimate_id)
            line_id = uuid4().hex
            line_no = as_int(count_row[0]) + 1
            _ = query(
                connection,
                """
                INSERT INTO estimate_lines VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    line_id,
                    estimate_id,
                    line_no,
                    item.line_kind,
                    item.product_id,
                    item.parent_product_id,
                    item.relation_id,
                    item.offer_operation,
                    item.offer_key,
                    item.item_name_snapshot,
                    item.spec_snapshot,
                    item.company_snapshot,
                    item.unit_snapshot,
                    item.unit_price_won_snapshot,
                    str(item.quantity),
                ),
            )
            _touch(connection, estimate_id)
            line = _read_line(connection, line_id)
            _ = connection.commit()
            return line

    def update_quantity(
        self,
        estimate_id: str,
        line_id: str,
        quantity: Decimal,
    ) -> EstimateLine:
        """Update one positive quantity without changing its snapshots."""
        _require_quantity(quantity)
        with connect(self.database) as connection:
            _ = connection.execute("BEGIN IMMEDIATE")
            _require_draft(connection, estimate_id)
            cursor = query(
                connection,
                """
                UPDATE estimate_lines SET quantity = ?
                WHERE id = ? AND estimate_id = ?
                """,
                (str(quantity), line_id, estimate_id),
            )
            if cursor.rowcount != 1:
                raise EstimateNotFoundError(line_id)
            _touch(connection, estimate_id)
            line = _read_line(connection, line_id)
            _ = connection.commit()
            return line

    def delete_line(self, estimate_id: str, line_id: str) -> None:
        """Delete one line and close its visible line-number gap."""
        with connect(self.database) as connection:
            _ = connection.execute("BEGIN IMMEDIATE")
            _require_draft(connection, estimate_id)
            found = query(
                connection,
                "SELECT line_no FROM estimate_lines WHERE id = ? AND estimate_id = ?",
                (line_id, estimate_id),
            ).fetchone()
            if found is None:
                raise EstimateNotFoundError(line_id)
            line_no = as_int(found[0])
            _ = query(connection, "DELETE FROM estimate_lines WHERE id = ?", (line_id,))
            _ = query(
                connection,
                """
                UPDATE estimate_lines SET line_no = line_no - 1
                WHERE estimate_id = ? AND line_no > ?
                """,
                (estimate_id, line_no),
            )
            _touch(connection, estimate_id)
            _ = connection.commit()

    def replace_draft(
        self,
        estimate_id: str,
        title: str,
        template_sha256: str,
        lines: tuple[tuple[str, EstimateLineInput], ...],
        comparison_seed: Callable[[sqlite3.Connection, tuple[EstimateLine, ...]], None],
    ) -> EstimateDraft:
        """Atomically persist one latest full document without quantity merging."""
        if len(lines) > MAX_ESTIMATE_LINES:
            raise EstimateFullError(estimate_id)
        for _line_id, item in lines:
            _require_quantity(item.quantity)
        now = datetime.now(UTC).isoformat()
        desired_lines = tuple(
            _document_line(line_id, line_no, item)
            for line_no, (line_id, item) in enumerate(lines, start=1)
        )
        previous_comparisons: list[SqlRow] = []
        with connect(self.database) as connection:
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
                    _line(row)
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
                _insert_line(connection, estimate_id, line)
            previous_by_id = {line.id: line for line in previous_lines}
            stable_ids = {
                line.id
                for line in desired_lines
                if (previous := previous_by_id.get(line.id)) is not None
                and (
                    previous.line_kind,
                    previous.product_id,
                    previous.parent_product_id,
                    previous.relation_id,
                    previous.offer_operation,
                    previous.offer_key,
                    previous.item_name_snapshot,
                    previous.spec_snapshot,
                    previous.company_snapshot,
                    previous.unit_snapshot,
                    previous.unit_price_won_snapshot,
                )
                == (
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

    def delete_draft_if_exists(self, estimate_id: str) -> None:
        """Delete one document, succeeding when it is already absent."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                "DELETE FROM estimate_drafts WHERE id = ?",
                (estimate_id,),
            )


def _require_draft(connection: sqlite3.Connection, estimate_id: str) -> None:
    found = query(
        connection,
        "SELECT 1 FROM estimate_drafts WHERE id = ?",
        (estimate_id,),
    ).fetchone()
    if found is None:
        raise EstimateNotFoundError(estimate_id)


def _touch(connection: sqlite3.Connection, estimate_id: str) -> None:
    _ = query(
        connection,
        "UPDATE estimate_drafts SET updated_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), estimate_id),
    )


def _read_line(connection: sqlite3.Connection, line_id: str) -> EstimateLine:
    row = query(
        connection,
        """
        SELECT id, line_no, line_kind, product_id, parent_product_id,
        relation_id, offer_operation, offer_key, item_name_snapshot,
        spec_snapshot, company_snapshot, unit_snapshot,
        unit_price_won_snapshot, quantity FROM estimate_lines WHERE id = ?
        """,
        (line_id,),
    ).fetchone()
    if row is None:
        raise EstimateNotFoundError(line_id)
    return _line(row)


def _document_line(
    line_id: str,
    line_no: int,
    item: EstimateLineInput,
) -> EstimateLine:
    return EstimateLine(
        id=line_id,
        line_no=line_no,
        line_kind=item.line_kind,
        product_id=item.product_id,
        parent_product_id=item.parent_product_id,
        relation_id=item.relation_id,
        offer_operation=item.offer_operation,
        offer_key=item.offer_key,
        item_name_snapshot=item.item_name_snapshot,
        spec_snapshot=item.spec_snapshot,
        company_snapshot=item.company_snapshot,
        unit_snapshot=item.unit_snapshot,
        unit_price_won_snapshot=item.unit_price_won_snapshot,
        quantity=item.quantity,
    )


def _insert_line(
    connection: sqlite3.Connection,
    estimate_id: str,
    line: EstimateLine,
) -> None:
    _ = query(
        connection,
        """
        INSERT INTO estimate_lines VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            line.id,
            estimate_id,
            line.line_no,
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
            str(line.quantity),
        ),
    )


def _line(row: SqlRow) -> EstimateLine:
    return EstimateLine(
        id=as_text(row[0]),
        line_no=as_int(row[1]),
        line_kind=_line_kind(as_text(row[2])),
        product_id=as_text(row[3]),
        parent_product_id=_optional_text(row[4]),
        relation_id=_optional_text(row[5]),
        offer_operation=_optional_text(row[6]),
        offer_key=_optional_text(row[7]),
        item_name_snapshot=as_text(row[8]),
        spec_snapshot=as_text(row[9]),
        company_snapshot=as_text(row[10]),
        unit_snapshot=as_text(row[11]),
        unit_price_won_snapshot=as_int(row[12]),
        quantity=Decimal(str(row[13])),
    )


def _optional_text(value: SqlValue) -> str | None:
    return None if value is None else as_text(value)


def _line_kind(value: str) -> Literal["main", "option"]:
    if value == "main":
        return "main"
    if value == "option":
        return "option"
    raise EstimateNotFoundError(value)


def _require_quantity(quantity: Decimal) -> None:
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(quantity)
