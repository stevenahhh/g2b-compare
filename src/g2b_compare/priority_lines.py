"""Read procurement-estimate style rows from the priority database."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Final, cast

from g2b_compare.priority_models import (
    PriorityLine,
    PriorityLinePage,
    PriorityLineSort,
    PriorityStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

_LINE_CTE: Final = """
WITH option_first AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY company_name, product_id ORDER BY source_row
    ) AS occurrence
    FROM priority_options
), lines AS (
    SELECT
        '0-' || product_id AS sort_key,
        '본품 [' || product_id || ']' AS path,
        category_name AS item_name,
        spec,
        unit,
        price_won,
        product_id,
        contract_method,
        delivery_condition,
        delivery_days,
        contract_end_date,
        company_name,
        detail_url,
        '본품' AS source_kind,
        NULL AS relation_id
    FROM priority_products
    UNION ALL
    SELECT
        '1-' || relation.parent_product_id || '-' || relation.option_product_id,
        '본품 [' || relation.parent_product_id || '] > 옵션 [' ||
            relation.option_product_id || ']',
        COALESCE(option.item_name, '추가선택품목'),
        COALESCE(NULLIF(option.spec, ''), relation.raw_label),
        COALESCE(product.unit, ''),
        relation.relation_price_won,
        relation.option_product_id,
        '', '', '', '',
        relation.company_name,
        relation.detail_url,
        '검증 옵션',
        relation.relation_id
    FROM verified_product_options AS relation
    LEFT JOIN option_first AS option
      ON option.company_name = relation.company_name
     AND option.product_id = relation.option_product_id
     AND option.occurrence = 1
    LEFT JOIN priority_products AS product
      ON product.product_id = relation.option_product_id
    WHERE relation.active = 1
    UNION ALL
    SELECT
        '2-' || relation.parent_product_id || '-' || relation.option_product_id,
        '미연결 옵션 후보 [' || relation.option_product_id || ']',
        COALESCE(option.item_name, '추가선택품목'),
        COALESCE(NULLIF(option.spec, ''), relation.raw_label),
        '',
        relation.price_won,
        relation.option_product_id,
        '', '', '', '',
        relation.company_name,
        '',
        '미연결 옵션 후보',
        NULL
    FROM priority_product_options AS relation
    LEFT JOIN option_first AS option
      ON option.company_name = relation.company_name
     AND option.product_id = relation.option_product_id
     AND option.occurrence = 1
    WHERE NOT EXISTS (
        SELECT 1 FROM verified_product_options AS verified
        WHERE verified.parent_product_id = relation.parent_product_id
          AND verified.option_product_id = relation.option_product_id
          AND verified.active = 1
    )
    UNION ALL
    SELECT
        '3-' || printf('%08d', option.source_row),
        '미연결 옵션 후보 [' || option.product_id || ']',
        option.item_name,
        option.spec,
        '',
        option.price_won,
        option.product_id,
        '', '', '', '',
        option.company_name,
        '',
        '미연결 옵션 후보',
        NULL
    FROM priority_options AS option
    WHERE NOT EXISTS (
        SELECT 1 FROM priority_product_options AS relation
        WHERE relation.company_name = option.company_name
          AND relation.option_product_id = option.product_id
    )
      AND NOT EXISTS (
        SELECT 1 FROM verified_product_options AS verified
        WHERE verified.company_name = option.company_name
          AND verified.option_product_id = option.product_id
          AND verified.active = 1
    )
)
"""
_LINE_WHERE: Final = (
    "WHERE lower(path || ' ' || item_name || ' ' || spec || ' ' || "
    "product_id || ' ' || company_name) LIKE ?"
)
_COUNT_SQL: Final = (
    _LINE_CTE + "SELECT COUNT(*) FROM lines " + _LINE_WHERE  # noqa: S608
)
def list_priority_lines(
    database: Path,
    query: str,
    *,
    page: int,
    page_size: int,
    sort: PriorityLineSort,
) -> PriorityLinePage:
    """Return one searchable page without loading the full workbook into RAM."""
    search = f"%{query.casefold()}%"
    offset = (page - 1) * page_size
    with sqlite3.connect(database) as connection:
        total_row = cast(
            "tuple[object, ...]",
            connection.execute(_COUNT_SQL, (search,)).fetchone(),
        )
        total = _integer(total_row[0])
        raw_rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(
                _select_sql(sort),
                (search, page_size, offset),
            ).fetchall(),
        )
    items = tuple(_line(row) for row in raw_rows)
    return PriorityLinePage(
        items=items,
        page=page,
        page_count=max(1, (total + page_size - 1) // page_size),
        total_count=total,
    )


def _select_sql(sort: PriorityLineSort) -> str:
    match sort:
        case PriorityLineSort.PRICE_ASC:
            order = "price_won ASC, item_name COLLATE NOCASE, product_id, sort_key"
        case PriorityLineSort.PRICE_DESC:
            order = "price_won DESC, item_name COLLATE NOCASE, product_id, sort_key"
        case PriorityLineSort.NAME_ASC:
            order = "item_name COLLATE NOCASE, price_won, product_id, sort_key"
        case PriorityLineSort.PRODUCT_ID_ASC:
            order = "product_id COLLATE NOCASE, item_name COLLATE NOCASE, sort_key"
    return (
        _LINE_CTE  # noqa: S608
        + "SELECT * FROM lines "
        + _LINE_WHERE
        + f" ORDER BY {order} LIMIT ? OFFSET ?"
    )


def read_priority_status(
    database: Path,
    *,
    pending_api_target_count: int,
) -> PriorityStatus:
    """Read compact collection counts for the CLI and web header."""
    with sqlite3.connect(database) as connection:
        return PriorityStatus(
            company_count=_count(connection, "priority_companies"),
            option_row_count=_count(connection, "priority_options"),
            unique_option_count=_query_count(
                connection,
                "SELECT COUNT(DISTINCT product_id) FROM priority_options",
            ),
            product_count=_count(connection, "priority_products"),
            relation_count=_relation_count(connection),
            pending_api_target_count=pending_api_target_count,
            pending_site_product_count=_query_count(
                connection,
                "SELECT COUNT(*) FROM priority_products WHERE site_crawled_at = ''",
            ),
        )


def _line(row: tuple[object, ...]) -> PriorityLine:
    return PriorityLine(
        path=_text(row[1]),
        item_name=_text(row[2]),
        spec=_text(row[3]),
        unit=_text(row[4]),
        price_won=_integer(row[5]),
        product_id=_text(row[6]),
        contract_method=_text(row[7]),
        delivery_condition=_text(row[8]),
        delivery_days=_text(row[9]),
        contract_end_date=_text(row[10]),
        company_name=_text(row[11]),
        detail_url=_text(row[12]),
        source_kind=_text(row[13]),
        relation_id=None if row[14] is None else _text(row[14]),
    )


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int) else int(str(value))


def _count(connection: sqlite3.Connection, table: str) -> int:
    allowed = {
        "priority_companies",
        "priority_options",
        "priority_products",
        "priority_contract_options",
        "priority_product_options",
        "verified_product_options",
    }
    if table not in allowed:
        raise ValueError(table)
    return _query_count(
        connection,
        f"SELECT COUNT(*) FROM {table}",  # noqa: S608
    )


def _query_count(connection: sqlite3.Connection, sql: str) -> int:
    row = cast("tuple[object, ...]", connection.execute(sql).fetchone())
    return _integer(row[0])


def _relation_count(connection: sqlite3.Connection) -> int:
    contract = _count(connection, "priority_contract_options")
    verified = _count(connection, "verified_product_options")
    return contract or verified or _count(connection, "priority_product_options")
