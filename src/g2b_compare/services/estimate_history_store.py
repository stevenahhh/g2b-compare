"""Persist the saved-estimate history list."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from g2b_compare.db.connection import connect
from g2b_compare.db.migrate import migrate
from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import (
    EstimateDraftSummary,
    EstimateNotFoundError,
)

if TYPE_CHECKING:
    from pathlib import Path


@final
class EstimateHistoryStore:
    """Transactional owner for saved-estimate list operations."""

    def __init__(self, database: Path) -> None:
        """Open the history store over one migrated application database."""
        self.database = database
        migrate(database)

    def discard_empty_drafts(self) -> None:
        """Remove abandoned drafts that never received an estimate line."""
        with connect(self.database) as connection:
            _ = query(
                connection,
                """
                DELETE FROM estimate_drafts
                WHERE NOT EXISTS (
                    SELECT 1 FROM estimate_lines
                    WHERE estimate_lines.estimate_id = estimate_drafts.id
                )
                """,
            )

    def list_saved_drafts(self) -> tuple[EstimateDraftSummary, ...]:
        """Return non-empty drafts ordered by their latest edit."""
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                SELECT draft.id, draft.title, draft.updated_at, COUNT(line.id)
                FROM estimate_drafts AS draft
                JOIN estimate_lines AS line ON line.estimate_id = draft.id
                GROUP BY draft.id, draft.title, draft.updated_at
                ORDER BY draft.updated_at DESC
                """,
            ).fetchall()
        return tuple(
            EstimateDraftSummary(
                id=as_text(row[0]),
                title=as_text(row[1]),
                updated_at=as_text(row[2]),
                line_count=as_int(row[3]),
            )
            for row in rows
        )

    def delete_draft(self, estimate_id: str) -> None:
        """Delete one persisted draft and its cascading snapshots."""
        with connect(self.database) as connection:
            cursor = query(
                connection,
                "DELETE FROM estimate_drafts WHERE id = ?",
                (estimate_id,),
            )
            if cursor.rowcount == 0:
                raise EstimateNotFoundError(estimate_id)
