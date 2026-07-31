"""Resolve trusted estimate-line snapshots from catalog records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import SqlRow, as_int, as_text, query
from g2b_compare.services import EstimateLineInput

from .estimate_models import RELATION_REQUIRED_DETAIL
from .estimate_text import (
    parse_option_label as _parse_option_label,
)
from .estimate_text import (
    text_or as _text_or,
)

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path


def resolve_selection(
    database: Path,
    product_id: str,
    parent_product_id: str | None,
    relation_id: str | None,
    quantity: Decimal,
) -> EstimateLineInput:
    """Resolve trusted display and price snapshots from the shared DB."""
    with connect(database) as connection:
        if relation_id is not None:
            relation = query(
                connection,
                """
                SELECT r.parent_product_id, r.parent_operation, r.parent_offer_key,
                r.company_name, r.raw_label, r.relation_price_won,
                p.category_name, p.spec, p.unit
                FROM verified_product_options AS r
                LEFT JOIN priority_products AS p
                ON p.product_id = r.option_product_id
                WHERE r.relation_id = ? AND r.option_product_id = ? AND r.active = 1
                """,
                (relation_id, product_id),
            ).fetchone()
            if relation is None and parent_product_id is not None:
                relation = query(
                    connection,
                    """
                    SELECT product_group.product_id, parent.operation,
                    parent.contract_number || ':' || parent.contract_sequence,
                    relation.company_name, relation.raw_label,
                    relation.relation_price_won, option.category_name,
                    option.spec, option.unit
                    FROM priority_contract_options AS relation
                    JOIN priority_product_contract_groups AS product_group
                    ON product_group.contract_group = relation.contract_group
                    JOIN priority_products AS parent
                    ON parent.product_id = product_group.product_id
                    LEFT JOIN priority_products AS option
                    ON option.product_id = relation.option_product_id
                    WHERE relation.relation_id = ?
                    AND relation.option_product_id = ?
                    AND product_group.product_id = ?
                    AND relation.active = 1
                    """,
                    (relation_id, product_id, parent_product_id),
                ).fetchone()
            if relation is None:
                raise HTTPException(status_code=400, detail=RELATION_REQUIRED_DETAIL)
            return _option_input(product_id, relation_id, quantity, relation)
        product = query(
            connection,
            """
            SELECT operation, contract_number, contract_sequence, category_name,
            spec, company_name, unit, price_won FROM priority_products
            WHERE product_id = ?
            """,
            (product_id,),
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=400, detail=RELATION_REQUIRED_DETAIL)
        return _main_input(product_id, quantity, product)


def _main_input(product_id: str, quantity: Decimal, row: SqlRow) -> EstimateLineInput:
    return EstimateLineInput(
        "main",
        product_id,
        None,
        None,
        as_text(row[0]),
        f"{as_text(row[1])}:{as_text(row[2])}",
        as_text(row[3]),
        as_text(row[4]),
        as_text(row[5]),
        as_text(row[6]),
        as_int(row[7]),
        quantity,
    )


def _option_input(
    product_id: str,
    relation_id: str,
    quantity: Decimal,
    row: SqlRow,
) -> EstimateLineInput:
    parsed_item, parsed_spec = _parse_option_label(as_text(row[4]))
    return EstimateLineInput(
        "option",
        product_id,
        as_text(row[0]),
        relation_id,
        as_text(row[1]),
        as_text(row[2]),
        parsed_item or _text_or(row[6], "옵션"),
        parsed_spec or _text_or(row[7], as_text(row[4])),
        as_text(row[3]),
        _text_or(row[8], "개"),
        as_int(row[5]),
        quantity,
    )
