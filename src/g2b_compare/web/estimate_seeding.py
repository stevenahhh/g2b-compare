"""Seed persisted comparison records for estimate lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.services import EstimateLine

from .estimate_main_candidates import rank_main_candidates as _rank_main_candidates
from .estimate_option_lookup import (
    stored_parent_alternatives as _stored_parent_alternatives,
)
from .estimate_option_matching import option_alternatives as _option_alternatives
from .estimate_policy import (
    choose_main_alternatives as _choose_main_alternatives,
)
from .estimate_policy import (
    koreanet_main as _koreanet_main,
)
from .estimate_policy import (
    requires_distinct_product_ids as _requires_distinct_product_ids,
)
from .estimate_records import (
    has_comparisons as _has_comparisons,
)
from .estimate_records import (
    insert_comparisons as _insert_comparisons,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from .estimate_models import ComparisonView
    from .estimate_models import MainCandidate as _MainCandidate


def seed_comparisons(database: Path, line: EstimateLine) -> None:
    """Pin the selection and two compatible alternatives as A/B/C."""
    with connect(database) as connection:
        seed_comparisons_in_transaction(connection, line)


def seed_document_comparisons_in_transaction(
    connection: sqlite3.Connection,
    lines: tuple[EstimateLine, ...],
) -> None:
    """Seed all comparisons after the full document has been inserted."""
    missing_ids = {line.id for line in lines if not _has_comparisons(connection, line)}
    if not missing_ids:
        return
    for line_id in missing_ids:
        _ = query(
            connection,
            "DELETE FROM estimate_comparisons WHERE estimate_line_id = ?",
            (line_id,),
        )
    contexts: dict[
        str, tuple[tuple[_MainCandidate, ...], tuple[_MainCandidate, ...]]
    ] = {}
    for line in lines:
        if line.line_kind != "main":
            continue
        options = tuple(
            item
            for item in lines
            if item.line_kind == "option" and item.parent_product_id == line.product_id
        )
        ranked = _rank_main_candidates(connection, line, options)
        baseline = _koreanet_main(ranked)
        chosen = _choose_main_alternatives(
            ranked,
            baseline,
            distinct_product_ids=_requires_distinct_product_ids(connection, line),
        )
        candidates = (
            () if baseline is None else (baseline.view, *(item.view for item in chosen))
        )
        if line.id in missing_ids:
            _insert_comparisons(connection, line, candidates)
        contexts[line.product_id] = (ranked, chosen)
    for line in lines:
        if line.line_kind != "option":
            continue
        ranked, chosen = contexts.get(line.parent_product_id or "", ((), ()))
        alternatives = (
            _option_alternatives(connection, line, ranked, chosen)
            if ranked or chosen
            else _standalone_option_alternatives(connection, line)
        )
        if line.id in missing_ids:
            _insert_comparisons(connection, line, alternatives)


def seed_comparisons_in_transaction(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> None:
    """Seed one line for legacy form routes."""
    if _has_comparisons(connection, line):
        return
    _ = query(
        connection,
        "DELETE FROM estimate_comparisons WHERE estimate_line_id = ?",
        (line.id,),
    )
    if line.line_kind == "main":
        ranked = _rank_main_candidates(connection, line, ())
        baseline = _koreanet_main(ranked)
        chosen = _choose_main_alternatives(
            ranked,
            baseline,
            distinct_product_ids=_requires_distinct_product_ids(connection, line),
        )
        alternatives = (
            () if baseline is None else (baseline.view, *(item.view for item in chosen))
        )
    else:
        chosen = _stored_parent_alternatives(connection, line)
        alternatives = (
            _option_alternatives(connection, line, chosen, chosen)
            if chosen
            else _standalone_option_alternatives(connection, line)
        )
    _insert_comparisons(connection, line, alternatives)


def _standalone_option_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[ComparisonView, ...]:
    parent = query(
        connection,
        """
        SELECT category_name, spec, company_name, unit, price_won
        FROM priority_products WHERE product_id = ?
        """,
        (line.parent_product_id,),
    ).fetchone()
    if parent is None or line.parent_product_id is None:
        return ()
    parent_line = EstimateLine(
        line.id,
        line.line_no,
        "main",
        line.parent_product_id,
        None,
        None,
        None,
        None,
        as_text(parent[0]),
        as_text(parent[1]),
        as_text(parent[2]),
        as_text(parent[3]),
        as_int(parent[4]),
        line.quantity,
    )
    ranked = _rank_main_candidates(connection, parent_line, (line,))
    chosen = _choose_main_alternatives(ranked, _koreanet_main(ranked))
    return _option_alternatives(connection, line, ranked, chosen)
