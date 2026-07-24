"""Read main products and their verified child options."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal, cast

from g2b_compare.normalize.text import normalize_search_text
from g2b_compare.priority_attributes import parse_product_attributes
from g2b_compare.priority_models import (
    CatalogOption,
    CatalogProduct,
    CatalogProductPage,
    PriorityLineSort,
)

_ACTIVE_PRODUCT: Final = """
FROM priority_products AS product
WHERE EXISTS (
    SELECT 1 FROM priority_product_offers AS offer
    WHERE offer.product_id = product.product_id AND offer.active = 1
)
AND NOT EXISTS (
    SELECT 1 FROM verified_product_options AS child_relation
    WHERE child_relation.option_product_id = product.product_id
      AND child_relation.active = 1
)
AND NOT EXISTS (
    SELECT 1 FROM priority_contract_options AS contract_child
    WHERE contract_child.option_product_id = product.product_id
      AND contract_child.active = 1
)
"""
_SELECT: Final = """
SELECT product.category_name, product.spec, product.unit, product.price_won,
       product.product_id, product.contract_method, product.delivery_condition,
       product.delivery_days, product.contract_end_date, product.company_name,
       product.detail_url, product.image_url, product.raw_json
"""


@dataclass(frozen=True, slots=True)
class _CatalogIndex:
    products: dict[str, CatalogProduct]
    documents: tuple[tuple[str, str], ...]
    legacy_documents: tuple[tuple[str, str], ...]
    group_documents: tuple[tuple[str, str], ...]
    group_products: dict[str, tuple[str, ...]]
    ordered_ids: dict[PriorityLineSort, tuple[str, ...]]

    def page(
        self,
        query: str,
        *,
        page: int,
        page_size: int,
        sort: PriorityLineSort,
    ) -> CatalogProductPage:
        """Search the warmed local index and return one sorted page."""
        terms = tuple(normalize_search_text(query).split())
        if terms:
            matches = {
                product_id
                for product_id, document in self.documents
                if _contains_all(document, terms)
            }
            matches.update(
                product_id
                for product_id, document in self.legacy_documents
                if _contains_all(document, terms) and product_id in self.products
            )
            for group, document in self.group_documents:
                if _contains_all(document, terms):
                    matches.update(
                        product_id
                        for product_id in self.group_products.get(group, ())
                        if product_id in self.products
                    )
        else:
            matches = set(self.products)
        ordered = self.ordered_ids[sort]
        offset = (page - 1) * page_size
        page_ids: list[str] = []
        for product_id in ordered:
            if product_id not in matches:
                continue
            if offset > 0:
                offset -= 1
                continue
            page_ids.append(product_id)
            if len(page_ids) == page_size:
                break
        total = len(matches)
        return CatalogProductPage(
            items=tuple(self.products[product_id] for product_id in page_ids),
            page=page,
            page_count=max(1, (total + page_size - 1) // page_size),
            total_count=total,
        )


_OPTIONS: Final = """
WITH option_first AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY company_name, product_id ORDER BY source_row
    ) AS occurrence
    FROM priority_options
), product_group_first AS (
    SELECT contract_group, MIN(product_id) AS product_id
    FROM priority_product_contract_groups
    WHERE (:parent_product_id = '' OR product_id = :parent_product_id)
    GROUP BY contract_group
), contract_rows AS (
SELECT product_group.product_id AS parent_product_id,
       COALESCE(option.item_name, '추가선택품목') AS item_name,
       COALESCE(NULLIF(relation.raw_label, ''), option.spec) AS spec,
       COALESCE(NULLIF(product.unit, ''), '개') AS unit,
       relation.relation_price_won AS relation_price_won,
       relation.option_product_id AS option_product_id,
       relation.company_name AS company_name,
       parent.detail_url AS detail_url,
       relation.relation_id AS relation_id,
       relation.relation_kind AS relation_kind,
       COALESCE(product.image_url, '') AS image_url,
       relation.position AS position
FROM product_group_first AS product_group
JOIN priority_contract_options AS relation
  ON relation.contract_group = product_group.contract_group
LEFT JOIN option_first AS option
  ON option.company_name = relation.company_name
 AND option.product_id = relation.option_product_id
 AND option.occurrence = 1
LEFT JOIN priority_products AS product
  ON product.product_id = relation.option_product_id
JOIN priority_products AS parent
  ON parent.product_id = product_group.product_id
WHERE (:company_name = '' OR relation.company_name = :company_name)
  AND relation.active = 1
), legacy_rows AS (
SELECT relation.parent_product_id AS parent_product_id,
       COALESCE(option.item_name, '추가선택품목') AS item_name,
       COALESCE(NULLIF(relation.raw_label, ''), option.spec) AS spec,
       COALESCE(NULLIF(product.unit, ''), '개') AS unit,
       relation.relation_price_won AS relation_price_won,
       relation.option_product_id AS option_product_id,
       relation.company_name AS company_name,
       relation.detail_url AS detail_url,
       relation.relation_id AS relation_id,
       relation.relation_kind AS relation_kind,
       COALESCE(product.image_url, '') AS image_url,
       relation.position AS position
FROM verified_product_options AS relation
LEFT JOIN option_first AS option
  ON option.company_name = relation.company_name
 AND option.product_id = relation.option_product_id
 AND option.occurrence = 1
LEFT JOIN priority_products AS product
  ON product.product_id = relation.option_product_id
WHERE (:parent_product_id = '' OR relation.parent_product_id = :parent_product_id)
  AND (:company_name = '' OR relation.company_name = :company_name)
  AND relation.active = 1
)
SELECT parent_product_id, item_name, spec, unit, relation_price_won,
       option_product_id, company_name, detail_url, relation_id, relation_kind,
       image_url, position
FROM contract_rows
UNION ALL
SELECT parent_product_id, item_name, spec, unit, relation_price_won,
       option_product_id, company_name, detail_url, relation_id, relation_kind,
       image_url, position
FROM legacy_rows
WHERE NOT EXISTS (
    SELECT 1 FROM contract_rows
    WHERE contract_rows.parent_product_id = legacy_rows.parent_product_id
)
ORDER BY position, option_product_id
"""


def list_catalog_products(
    database: Path,
    query: str,
    *,
    page: int,
    page_size: int,
    sort: PriorityLineSort,
) -> CatalogProductPage:
    """Return main products, including parents matched through child options."""
    return _current_index(database).page(
        query,
        page=page,
        page_size=page_size,
        sort=sort,
    )


def warm_catalog_index(database: Path) -> None:
    """Build the catalog index before the server accepts UI searches."""
    _ = _current_index(database)


def _current_index(database: Path) -> _CatalogIndex:
    resolved = database.resolve()
    wal = Path(f"{resolved}-wal")
    return _load_index(resolved, _stamp(resolved), _stamp(wal))


def _stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=1)
def _load_index(
    database: Path,
    database_stamp: tuple[int, int],
    wal_stamp: tuple[int, int],
) -> _CatalogIndex:
    _ = database_stamp, wal_stamp
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(_SELECT + _ACTIVE_PRODUCT).fetchall(),
        )
        option_text = _option_text(connection)
        legacy_documents = _relation_documents(
            connection,
            """
            SELECT parent_product_id, option_product_id, raw_label, company_name
            FROM verified_product_options WHERE active = 1
            """,
            option_text,
        )
        group_documents = _relation_documents(
            connection,
            """
            SELECT contract_group, option_product_id, raw_label, company_name
            FROM priority_contract_options WHERE active = 1
            """,
            option_text,
        )
        group_rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(
                """
                SELECT contract_group, product_id
                FROM priority_product_contract_groups
                """
            ).fetchall(),
        )
    products = {_text(row[4]): _product(row) for row in rows}
    documents = tuple(
        (
            product.product_id,
            _product_document(product),
        )
        for product in products.values()
    )
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in group_rows:
        grouped[_text(row[0])].append(_text(row[1]))
    ordered_ids = {
        PriorityLineSort.PRICE_ASC: tuple(
            sorted(
                products,
                key=lambda product_id: (
                    products[product_id].price_won,
                    products[product_id].item_name,
                    product_id,
                ),
            )
        ),
        PriorityLineSort.PRICE_DESC: tuple(
            sorted(
                products,
                key=lambda product_id: (
                    -products[product_id].price_won,
                    products[product_id].item_name,
                    product_id,
                ),
            )
        ),
        PriorityLineSort.NAME_ASC: tuple(
            sorted(
                products,
                key=lambda product_id: (
                    products[product_id].item_name.casefold(),
                    product_id,
                ),
            )
        ),
        PriorityLineSort.PRODUCT_ID_ASC: tuple(
            sorted(
                products,
                key=lambda product_id: (
                    product_id.casefold(),
                    products[product_id].item_name,
                ),
            )
        ),
    }
    return _CatalogIndex(
        products=products,
        documents=documents,
        legacy_documents=legacy_documents,
        group_documents=group_documents,
        group_products={key: tuple(value) for key, value in grouped.items()},
        ordered_ids=ordered_ids,
    )


def _option_text(connection: sqlite3.Connection) -> dict[tuple[str, str], str]:
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(
            """
            SELECT company_name, product_id, item_name, spec
            FROM priority_options ORDER BY source_row
            """
        ).fetchall(),
    )
    result: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (_text(row[0]), _text(row[1]))
        _ = result.setdefault(key, f"{_text(row[2])} {_text(row[3])}")
    return result


def _relation_documents(
    connection: sqlite3.Connection,
    query: str,
    option_text: dict[tuple[str, str], str],
) -> tuple[tuple[str, str], ...]:
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(query).fetchall(),
    )
    documents: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        owner = _text(row[0])
        product_id = _text(row[1])
        company_name = _text(row[3])
        documents[owner].extend(
            (
                product_id,
                _text(row[2]),
                company_name,
                option_text.get((company_name, product_id), ""),
            )
        )
    return tuple(
        (owner, normalize_search_text(" ".join(parts)))
        for owner, parts in documents.items()
    )


def _product_document(product: CatalogProduct) -> str:
    item_name, spec = product.item_name, product.spec
    product_id, company_name = product.product_id, product.company_name
    attributes = " ".join(
        f"{attribute.name} {attribute.value} {attribute.unit}"
        for attribute in product.attributes
    )
    return normalize_search_text(
        f"{item_name} {spec} {product_id} {company_name} {attributes}"
    )


def _contains_all(document: str, terms: tuple[str, ...]) -> bool:
    return all(term in document for term in terms)


def list_catalog_options(
    database: Path,
    parent_product_id: str,
) -> tuple[CatalogOption, ...]:
    """Return only active verified options belonging to one parent."""
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(
                _OPTIONS,
                {"parent_product_id": parent_product_id, "company_name": ""},
            ).fetchall(),
        )
    return tuple(_option(row) for row in rows)


def list_catalog_options_for_company(
    database: Path,
    company_name: str,
) -> tuple[CatalogOption, ...]:
    """Return all active verified options sold by one company."""
    with sqlite3.connect(database) as connection:
        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute(
                _OPTIONS,
                {"parent_product_id": "", "company_name": company_name},
            ).fetchall(),
        )
    return tuple(_option(row) for row in rows)


def _product(row: tuple[object, ...]) -> CatalogProduct:
    return CatalogProduct(
        item_name=_text(row[0]),
        spec=_text(row[1]),
        unit=_text(row[2]),
        price_won=_integer(row[3]),
        product_id=_text(row[4]),
        contract_method=_text(row[5]),
        delivery_condition=_text(row[6]),
        delivery_days=_text(row[7]),
        contract_end_date=_text(row[8]),
        company_name=_text(row[9]),
        detail_url=_text(row[10]),
        image_url=_text(row[11]),
        attributes=parse_product_attributes(_text(row[12])),
    )


def _option(row: tuple[object, ...]) -> CatalogOption:
    item_name, spec = _option_name_spec(_text(row[1]), _text(row[2]))
    return CatalogOption(
        parent_product_id=_text(row[0]),
        item_name=item_name,
        spec=spec,
        unit=_text(row[3]),
        price_won=_integer(row[4]),
        product_id=_text(row[5]),
        company_name=_text(row[6]),
        detail_url=_text(row[7]),
        relation_id=_text(row[8]),
        relation_kind=cast("Literal['additional', 'component']", _text(row[9])),
        image_url=_text(row[10]),
    )


def _option_name_spec(item_name: str, spec: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"\[[^]]+\]\s*\[\d{8}\]\s*([^,]+),\s*(.*?)\s*:\s*[\d,]+\s*",
        spec,
    )
    if match is not None:
        return match.group(1).strip(), match.group(2).strip()
    if item_name not in {"추가선택품목", "선택품목", "옵션"}:
        return item_name, spec
    return item_name, spec


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _integer(value: object) -> int:
    return value if isinstance(value, int) else int(str(value))
