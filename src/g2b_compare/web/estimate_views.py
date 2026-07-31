"""Read persisted comparison snapshots into editor views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.priority_attributes import parse_product_attributes

from .estimate_models import ComparisonView
from .estimate_text import text_or as _text_or

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.services import EstimateDraft


def comparison_views(
    database: Path,
    draft: EstimateDraft,
) -> dict[str, tuple[ComparisonView, ...]]:
    """Return ordered comparison snapshots for every visible line."""
    result: dict[str, tuple[ComparisonView, ...]] = {}
    with connect(database) as connection:
        for line in draft.lines:
            rows = query(
                connection,
                """
                SELECT comparison.slot, comparison.product_id,
                comparison.relation_id, comparison.company_snapshot,
                comparison.spec_snapshot, comparison.price_won_snapshot,
                COALESCE(product.raw_json, parent.raw_json),
                COALESCE(
                    NULLIF(relation.detail_url, ''),
                    NULLIF(product.detail_url, ''),
                    parent.detail_url,
                    ''
                )
                FROM estimate_comparisons AS comparison
                LEFT JOIN priority_products AS product
                ON product.product_id = comparison.product_id
                LEFT JOIN priority_products AS parent
                ON parent.product_id = ?
                LEFT JOIN verified_product_options AS relation
                ON relation.relation_id = comparison.relation_id
                WHERE estimate_line_id = ? ORDER BY slot
                """,
                (line.parent_product_id, line.id),
            ).fetchall()
            result[line.id] = tuple(
                ComparisonView(
                    as_text(row[0]),
                    as_text(row[1]),
                    None if row[2] is None else as_text(row[2]),
                    as_text(row[3]),
                    as_text(row[4]),
                    as_int(row[5]),
                    parse_product_attributes(_text_or(row[6], "{}")),
                    as_text(row[7]),
                )
                for row in rows
            )
    return result
