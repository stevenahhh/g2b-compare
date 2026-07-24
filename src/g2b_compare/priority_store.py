"""SQLite persistence for priority companies, products, and options."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.migrate import migrate
from g2b_compare.priority_catalog import list_catalog_options, list_catalog_products
from g2b_compare.priority_lines import list_priority_lines, read_priority_status
from g2b_compare.priority_models import (
    CatalogOption,
    CatalogProductPage,
    CrawlTarget,
    PriorityDataset,
    PriorityLinePage,
    PriorityLineSort,
    PriorityStatus,
    ProductOptionRelation,
    ProductOptionTarget,
)
from g2b_compare.priority_schema import (
    SCHEMA,
    SELECT_PENDING_SITE,
    SELECT_PENDING_SITE_LIMIT,
    UPDATE_SITE_RESULT,
    UPSERT_CRAWL_STATE,
    UPSERT_PRODUCT,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from g2b_compare.sources.shopping_mall import CatalogRecord, QuarantinedRecord

SHOP_HOME = "https://shop.g2b.go.kr/"
_MAS_CONTRACT = re.compile(r"^[0-9A-Z]+\d{2}$")


@final
class PriorityStore:
    """Small transactional boundary around the priority SQLite tables."""

    def __init__(self, database: Path) -> None:
        """Create missing priority tables in the selected database."""
        self.database: Path = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            _ = connection.executescript(SCHEMA)
        migrate(self.database)

    def replace_dataset(self, dataset: PriorityDataset) -> None:
        """Replace only workbook-owned tables in one transaction."""
        with sqlite3.connect(self.database) as connection:
            _ = connection.execute("DELETE FROM priority_options")
            _ = connection.execute("DELETE FROM priority_companies")
            _ = connection.executemany(
                "INSERT INTO priority_companies VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        item.name,
                        item.source_row,
                        item.location,
                        item.company_type,
                        item.declared_product_count,
                        item.contract_end_date,
                    )
                    for item in dataset.companies
                ),
            )
            _ = connection.executemany(
                "INSERT INTO priority_options VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        item.source_row,
                        item.company_name,
                        item.kind,
                        item.product_id,
                        item.item_name,
                        item.spec,
                        item.price_won,
                        item.details,
                    )
                    for item in dataset.options
                ),
            )

    def crawl_targets(self, operations: Sequence[Operation]) -> tuple[CrawlTarget, ...]:
        """Return every incomplete company and operation cursor."""
        with sqlite3.connect(self.database) as connection:
            company_rows = cast(
                "list[tuple[object, ...]]",
                connection.execute(
                    "SELECT name, location FROM priority_companies ORDER BY source_row"
                ).fetchall(),
            )
            state_rows = cast(
                "list[tuple[object, ...]]",
                connection.execute(
                    """
                    SELECT company_name, operation, next_page, complete
                    FROM priority_crawl_state
                    """
                ).fetchall(),
            )
        states = {
            (_text(row[0]), _text(row[1])): (_integer(row[2]), bool(row[3]))
            for row in state_rows
        }
        targets: list[CrawlTarget] = []
        for row in company_rows:
            company = _text(row[0])
            for operation in operations:
                next_page, complete = states.get((company, str(operation)), (1, False))
                if not complete:
                    targets.append(
                        CrawlTarget(
                            company_name=company,
                            location=_text(row[1]),
                            operation=str(operation),
                            next_page=next_page,
                        )
                    )
        return tuple(targets)

    def save_catalog_page(  # noqa: PLR0913
        self,
        *,
        company_name: str,
        operation: Operation,
        page_number: int,
        page_size: int,
        total_count: int,
        records: Iterable[CatalogRecord],
        observed_at: datetime,
        quarantined: Iterable[QuarantinedRecord] = (),
        request_fingerprint: str = "",
    ) -> None:
        """Persist a page and advance its resume cursor atomically."""
        complete = page_number * page_size >= total_count
        record_rows = tuple(records)
        quarantine_rows = tuple(quarantined)
        observed = observed_at.astimezone(UTC).isoformat()
        with sqlite3.connect(self.database) as connection:
            if page_number == 1:
                _ = connection.execute(
                    """
                    UPDATE priority_product_offers SET active = 0
                    WHERE company_name = ? AND operation = ?
                    """,
                    (company_name, str(operation)),
                )
                _ = connection.execute(
                    """
                    DELETE FROM priority_company_crawl_pages
                    WHERE company_name = ? AND operation = ?
                    """,
                    (company_name, str(operation)),
                )
                _ = connection.execute(
                    """
                    DELETE FROM priority_company_quarantine
                    WHERE company_name = ? AND operation = ?
                    """,
                    (company_name, str(operation)),
                )
            for record in record_rows:
                fields = record.raw_fields
                contract_number, contract_sequence = record.identity.stable_source_key
                _ = connection.execute(
                    UPSERT_PRODUCT,
                    (
                        record.product_id,
                        str(operation),
                        contract_number,
                        contract_sequence,
                        record.classification_number,
                        record.category_name,
                        record.detail_category_number,
                        record.spec_name,
                        _field(fields, "cntrctCorpNm") or company_name,
                        _field(fields, "prdctUnit"),
                        _amount(record.contract_price),
                        _field(fields, "cntrctMthdNm"),
                        _field(fields, "prdctDlvryCndtnNm"),
                        _field(fields, "dlvrTmlmtDaynum"),
                        _field(fields, "cntrctEndDate"),
                        record.image_url,
                        _detail_url(operation, contract_number, contract_sequence),
                        json.dumps(
                            fields,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        observed,
                    ),
                )
                offer_key = f"{contract_number}:{contract_sequence}"
                _ = connection.execute(
                    """
                    INSERT INTO priority_product_offers
                    (operation, offer_key, product_id, company_name, price_won,
                    unit, contract_method, delivery_condition, delivery_days,
                    contract_end_date, image_url, detail_url, raw_json,
                    observed_at, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(operation, offer_key) DO UPDATE SET
                    product_id=excluded.product_id,
                    company_name=excluded.company_name,
                    price_won=excluded.price_won, unit=excluded.unit,
                    contract_method=excluded.contract_method,
                    delivery_condition=excluded.delivery_condition,
                    delivery_days=excluded.delivery_days,
                    contract_end_date=excluded.contract_end_date,
                    image_url=excluded.image_url, detail_url=excluded.detail_url,
                    raw_json=excluded.raw_json,
                    observed_at=excluded.observed_at, active=1
                    """,
                    (
                        str(operation),
                        offer_key,
                        record.product_id,
                        _field(fields, "cntrctCorpNm") or company_name,
                        _amount(record.contract_price),
                        _field(fields, "prdctUnit"),
                        _field(fields, "cntrctMthdNm"),
                        _field(fields, "prdctDlvryCndtnNm"),
                        _field(fields, "dlvrTmlmtDaynum"),
                        _field(fields, "cntrctEndDate"),
                        record.image_url,
                        _detail_url(operation, contract_number, contract_sequence),
                        json.dumps(fields, ensure_ascii=False, sort_keys=True),
                        observed,
                    ),
                )
            _ = connection.execute(
                """
                INSERT INTO priority_company_crawl_pages VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_name, operation, page_number) DO UPDATE SET
                page_size=excluded.page_size,
                provider_total_count=excluded.provider_total_count,
                accepted_count=excluded.accepted_count,
                quarantined_count=excluded.quarantined_count,
                request_fingerprint=excluded.request_fingerprint,
                observed_at=excluded.observed_at
                """,
                (
                    company_name,
                    str(operation),
                    page_number,
                    page_size,
                    total_count,
                    len(record_rows),
                    len(quarantine_rows),
                    request_fingerprint,
                    observed,
                ),
            )
            _ = connection.execute(
                """
                DELETE FROM priority_company_quarantine
                WHERE company_name = ? AND operation = ? AND page_number = ?
                """,
                (company_name, str(operation), page_number),
            )
            _ = connection.executemany(
                """
                INSERT INTO priority_company_quarantine VALUES
                (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        company_name,
                        str(operation),
                        page_number,
                        row_number,
                        row.reason,
                        json.dumps(
                            row.raw_fields,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        observed,
                    )
                    for row_number, row in enumerate(quarantine_rows, start=1)
                ),
            )
            _ = connection.execute(
                UPSERT_CRAWL_STATE,
                (company_name, str(operation), page_number + 1, int(complete)),
            )

    def pending_site_products(self, limit: int) -> tuple[str, ...]:
        """Return API products not yet inspected on the live detail page."""
        with sqlite3.connect(self.database) as connection:
            if limit > 0:
                cursor = connection.execute(
                    SELECT_PENDING_SITE_LIMIT,
                    (limit,),
                )
            else:
                cursor = connection.execute(SELECT_PENDING_SITE)
            rows = cast("list[tuple[object, ...]]", cursor.fetchall())
        return tuple(_text(row[0]) for row in rows)

    def pending_site_targets(self, limit: int) -> tuple[ProductOptionTarget, ...]:
        """Return uncrawled products with their official contract grouping key."""
        query = """
            SELECT product_id,
                   json_extract(raw_json, '$.ctrtItemMngNo'),
                   COALESCE(
                       NULLIF(json_extract(raw_json, '$.ctrtNo'), '') || ':' ||
                       COALESCE(json_extract(raw_json, '$.ctrtChgOrd'), ''),
                       json_extract(raw_json, '$.ctrtItemMngNo')
                   )
            FROM priority_products
            WHERE site_crawled_at = ''
            ORDER BY product_id
        """
        parameters: tuple[int, ...] = ()
        if limit > 0:
            query += " LIMIT ?"
            parameters = (limit,)
        with sqlite3.connect(self.database) as connection:
            rows = cast(
                "list[tuple[object, ...]]",
                connection.execute(query, parameters).fetchall(),
            )
        return tuple(
            ProductOptionTarget(
                product_id=_text(row[0]),
                contract_item_number=_text(row[1]),
                contract_group=_text(row[2]),
            )
            for row in rows
        )

    def save_contract_group_result(
        self,
        targets: Sequence[ProductOptionTarget],
        options: Sequence[ProductOptionRelation],
        *,
        status: str,
    ) -> None:
        """Persist one shared official dropdown result for every group product."""
        if not targets:
            return
        now = datetime.now(UTC).isoformat()
        product_ids = tuple(target.product_id for target in targets)
        with sqlite3.connect(self.database) as connection:
            if status == "retry":
                _ = connection.executemany(
                    UPDATE_SITE_RESULT,
                    ((status, "", product_id) for product_id in product_ids),
                )
                return
            group = targets[0].contract_group
            company_row = cast(
                "tuple[object, ...] | None",
                connection.execute(
                    "SELECT company_name FROM priority_products WHERE product_id = ?",
                    (targets[0].product_id,),
                ).fetchone(),
            )
            if company_row is None:
                return
            company_name = _text(company_row[0])
            _ = connection.executemany(
                """
                INSERT INTO priority_product_contract_groups VALUES (?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    contract_group=excluded.contract_group
                """,
                ((product_id, group) for product_id in product_ids),
            )
            _ = connection.execute(
                "DELETE FROM priority_contract_options WHERE contract_group = ?",
                (group,),
            )
            _ = connection.executemany(
                """
                INSERT INTO priority_contract_options VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    (
                        group,
                        hashlib.sha256(
                            f"{group}|{option.kind}|{position}|{option.product_id}".encode()
                        ).hexdigest(),
                        option.product_id,
                        option.kind,
                        position,
                        company_name,
                        option.raw_label,
                        option.price_won,
                        now,
                    )
                    for position, option in enumerate(options)
                ),
            )
            _ = connection.executemany(
                UPDATE_SITE_RESULT,
                ((status, now, product_id) for product_id in product_ids),
            )

    def save_site_result(
        self,
        parent_product_id: str,
        options: Iterable[ProductOptionRelation],
        *,
        status: str,
    ) -> None:
        """Replace verified relations for one parent and mark it inspected."""
        now = datetime.now(UTC).isoformat()
        option_rows = tuple(options)
        with sqlite3.connect(self.database) as connection:
            row = cast(
                "tuple[object, ...] | None",
                connection.execute(
                    """
                    SELECT operation, contract_number, contract_sequence,
                    company_name, detail_url FROM priority_products
                    WHERE product_id = ?
                    """,
                    (parent_product_id,),
                ).fetchone(),
            )
            if row is None:
                return
            operation = _text(row[0])
            offer_key = f"{_text(row[1])}:{_text(row[2])}"
            company_name = _text(row[3])
            detail_url = _text(row[4])
            if status != "retry":
                _ = connection.execute(
                    "DELETE FROM priority_product_options WHERE parent_product_id = ?",
                    (parent_product_id,),
                )
                _ = connection.executemany(
                    "INSERT INTO priority_product_options VALUES (?, ?, ?, ?, ?)",
                    (
                        (
                            parent_product_id,
                            option.product_id,
                            company_name,
                            option.raw_label,
                            option.price_won,
                        )
                        for option in option_rows
                    ),
                )
                _ = connection.execute(
                    """
                    DELETE FROM verified_product_options
                    WHERE parent_operation = ? AND parent_offer_key = ?
                    """,
                    (operation, offer_key),
                )
                _ = connection.executemany(
                    """
                    INSERT INTO verified_product_options VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        (
                            hashlib.sha256(
                                (
                                    f"{operation}|{offer_key}|{option.kind}|"
                                    f"{position}|{option.product_id}"
                                ).encode()
                            ).hexdigest(),
                            operation,
                            offer_key,
                            parent_product_id,
                            option.product_id,
                            option.kind,
                            position,
                            company_name,
                            option.raw_label,
                            option.price_won,
                            detail_url,
                            now,
                        )
                        for position, option in enumerate(option_rows)
                        if option.product_id != parent_product_id
                    ),
                )
            _ = connection.execute(
                UPDATE_SITE_RESULT,
                (status, "" if status == "retry" else now, parent_product_id),
            )

    def status(self) -> PriorityStatus:
        """Return compact persisted collection counts."""
        return read_priority_status(
            self.database,
            pending_api_target_count=len(self.crawl_targets(tuple(Operation)[:3])),
        )

    def list_lines(
        self,
        query: str,
        *,
        page: int,
        page_size: int,
        sort: PriorityLineSort = PriorityLineSort.PRICE_ASC,
    ) -> PriorityLinePage:
        """Return one searchable procurement-estimate style page."""
        return list_priority_lines(
            self.database,
            query,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    def list_catalog_products(
        self,
        query: str,
        *,
        page: int,
        page_size: int,
        sort: PriorityLineSort,
    ) -> CatalogProductPage:
        """Return one main-product-only catalog page."""
        return list_catalog_products(
            self.database,
            query,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    def list_catalog_options(self, parent_product_id: str) -> tuple[CatalogOption, ...]:
        """Return verified options for one parent product."""
        return list_catalog_options(self.database, parent_product_id)


def _field(fields: Mapping[str, object], key: str) -> str:
    return _text(fields.get(key))


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int) else int(str(value))


def _amount(raw: str) -> int:
    value = raw.replace(",", "").strip()
    return int(float(value)) if value else 0


def _detail_url(
    operation: Operation, contract_number: str, contract_sequence: str
) -> str:
    if operation is Operation.GET_SHOPPING_MALL_PRODUCT_INFO and contract_number:
        return f"{SHOP_HOME}link/GMSF001_01/?ctrtItemMngNo={contract_number}"
    if (
        operation is not Operation.GET_MAS_CONTRACT_PRODUCT_INFO
        or _MAS_CONTRACT.fullmatch(contract_number) is None
        or not contract_sequence.isdecimal()
    ):
        return SHOP_HOME
    serial = f"{int(contract_sequence):07d}"
    item_key = f"{contract_number[:-2]}_1{contract_number[-2:]}{serial}"
    return f"{SHOP_HOME}link/GMSF001_01/?ctrtItemMngNo={item_key}"
