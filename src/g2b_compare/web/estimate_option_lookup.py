"""Read option candidates and stored parent comparison records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import as_int, as_text, query

from .estimate_models import (
    ALTERNATIVE_COUNT,
    KOREANET_COMPANY,
    ComparisonView,
)
from .estimate_models import (
    MainCandidate as _MainCandidate,
)
from .estimate_models import (
    OptionCandidate as _OptionCandidate,
)
from .estimate_text import (
    parse_option_label as _parse_option_label,
)
from .estimate_text import (
    text_or as _text_or,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine


def same_option_relation_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[ComparisonView, ...]:
    """Return alternatives already verified through the selected relation."""
    rows = query(
        connection,
        """
        SELECT relation_id, option_product_id, company_name, raw_label,
        relation_price_won
        FROM priority_contract_options
        WHERE option_product_id = ? AND active = 1
        AND company_name <> ? AND relation_price_won >= ?
        ORDER BY relation_price_won, company_name, relation_id
        """,
        (line.product_id, KOREANET_COMPANY, line.unit_price_won_snapshot),
    ).fetchall()
    alternatives: list[ComparisonView] = []
    companies = {KOREANET_COMPANY}
    for row in rows:
        company = as_text(row[2])
        if company in companies:
            continue
        _item_name, spec = _parse_option_label(as_text(row[3]))
        alternatives.append(
            ComparisonView(
                "",
                as_text(row[1]),
                as_text(row[0]),
                company,
                spec,
                as_int(row[4]),
            )
        )
        companies.add(company)
        if len(alternatives) == ALTERNATIVE_COUNT:
            break
    return tuple(alternatives)


def group_option_candidates(
    connection: sqlite3.Connection,
    main_product_id: str,
) -> tuple[_OptionCandidate, ...]:
    """Return verified options attached to one main product group."""
    rows = query(
        connection,
        """
        SELECT relation.relation_id, relation.option_product_id,
        relation.company_name, relation.raw_label, relation.relation_price_won,
        option.item_name, option.spec, option.details
        FROM priority_product_contract_groups AS product_group
        JOIN priority_contract_options AS relation
        ON relation.contract_group = product_group.contract_group
        LEFT JOIN priority_options AS option
        ON option.company_name = relation.company_name
        AND option.product_id = relation.option_product_id
        AND option.price_won = relation.relation_price_won
        WHERE product_group.product_id = ? AND relation.active = 1
        ORDER BY relation.position, option.source_row
        """,
        (main_product_id,),
    ).fetchall()
    result: list[_OptionCandidate] = []
    seen: set[str] = set()
    for row in rows:
        relation_id = as_text(row[0])
        if relation_id in seen:
            continue
        seen.add(relation_id)
        raw_label = as_text(row[3])
        parsed_item, parsed_spec = _parse_option_label(raw_label)
        item_name = _text_or(row[5], parsed_item)
        spec = _text_or(row[6], parsed_spec)
        details = _text_or(row[7], "")
        result.append(
            _OptionCandidate(
                ComparisonView(
                    "",
                    as_text(row[1]),
                    relation_id,
                    as_text(row[2]),
                    spec,
                    as_int(row[4]),
                ),
                item_name,
                f"{spec} {details}",
            )
        )
    return tuple(result)


def company_option_candidates(
    connection: sqlite3.Connection,
    company: str,
) -> tuple[_OptionCandidate, ...]:
    """Return option candidates sold by one comparison company."""
    option_rows = query(
        connection,
        """
        SELECT product_id, item_name, spec, price_won, details
        FROM priority_options WHERE company_name = ? ORDER BY source_row
        """,
        (company,),
    ).fetchall()
    result = [
        _OptionCandidate(
            ComparisonView(
                "", as_text(row[0]), None, company, as_text(row[2]), as_int(row[3])
            ),
            as_text(row[1]),
            f"{as_text(row[2])} {as_text(row[4])}",
        )
        for row in option_rows
    ]
    relation_rows = query(
        connection,
        """
        SELECT relation_id, option_product_id, raw_label, relation_price_won
        FROM priority_contract_options
        WHERE company_name = ? AND active = 1 ORDER BY position
        """,
        (company,),
    ).fetchall()
    for row in relation_rows:
        item_name, spec = _parse_option_label(as_text(row[2]))
        result.append(
            _OptionCandidate(
                ComparisonView(
                    "", as_text(row[1]), as_text(row[0]), company, spec, as_int(row[3])
                ),
                item_name,
                spec,
            )
        )
    return tuple(result)


def stored_parent_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[_MainCandidate, ...]:
    """Read already pinned alternatives from the parent line."""
    rows = query(
        connection,
        """
        SELECT comparison.product_id, comparison.company_snapshot,
        comparison.spec_snapshot, comparison.price_won_snapshot,
        COALESCE(company.source_row, 2147483647)
        FROM estimate_lines AS parent
        JOIN estimate_comparisons AS comparison
        ON comparison.estimate_line_id = parent.id
        LEFT JOIN priority_companies AS company
        ON company.name = comparison.company_snapshot
        WHERE parent.estimate_id = (
            SELECT estimate_id FROM estimate_lines WHERE id = ?
        )
        AND parent.product_id = ? AND parent.line_kind = 'main'
        AND comparison.slot IN ('B', 'C') ORDER BY comparison.slot
        """,
        (line.id, line.parent_product_id),
    ).fetchall()
    return tuple(
        _MainCandidate(
            ComparisonView(
                "",
                as_text(row[0]),
                None,
                as_text(row[1]),
                as_text(row[2]),
                as_int(row[3]),
            ),
            as_int(row[4]),
            (0, 0, 0, 0, 0, 0, 0, as_text(row[0])),
        )
        for row in rows
    )
