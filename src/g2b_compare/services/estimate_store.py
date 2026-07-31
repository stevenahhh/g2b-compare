"""Public estimate persistence facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from g2b_compare.db.migrate import migrate

from .estimate_documents import (
    DocumentReplacement,
    refresh_comparisons,
    replace_draft,
)
from .estimate_drafts import (
    create_draft,
    delete_draft_if_exists,
    draft_count,
    get_draft,
)
from .estimate_lines import add_line, delete_line, update_quantity
from .estimate_models import EstimateFullError

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from decimal import Decimal
    from pathlib import Path

    from .estimate_models import EstimateDraft, EstimateLine, EstimateLineInput

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
        return create_draft(self.database, title, template_sha256)

    def draft_count(self) -> int:
        """Return the number used for the next visible draft sequence."""
        return draft_count(self.database)

    def get_draft(self, estimate_id: str) -> EstimateDraft:
        """Return one draft and its current ordered snapshots."""
        return get_draft(self.database, estimate_id)

    def add_line(self, estimate_id: str, item: EstimateLineInput) -> EstimateLine:
        """Append a snapshot or merge an identical verified option relation."""
        return add_line(self.database, MAX_ESTIMATE_LINES, estimate_id, item)

    def update_quantity(
        self,
        estimate_id: str,
        line_id: str,
        quantity: Decimal,
    ) -> EstimateLine:
        """Update one positive quantity without changing its snapshots."""
        return update_quantity(self.database, estimate_id, line_id, quantity)

    def delete_line(self, estimate_id: str, line_id: str) -> None:
        """Delete one line and close its visible line-number gap."""
        delete_line(self.database, estimate_id, line_id)

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
        return replace_draft(
            self.database,
            estimate_id,
            DocumentReplacement(title, template_sha256, lines),
            comparison_seed,
        )

    def refresh_comparisons(
        self,
        estimate_id: str,
        comparison_seed: Callable[[sqlite3.Connection, tuple[EstimateLine, ...]], None],
    ) -> EstimateDraft:
        """Atomically reseed current comparison snapshots."""
        return refresh_comparisons(self.database, estimate_id, comparison_seed)

    def delete_draft_if_exists(self, estimate_id: str) -> None:
        """Delete one document, succeeding when it is already absent."""
        delete_draft_if_exists(self.database, estimate_id)
