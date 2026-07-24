"""Publish an inactive candidate materialization atomically."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, query
from g2b_compare.normalize.text import normalize_text

if TYPE_CHECKING:
    from pathlib import Path

    from .attributes import ProductAttribute
    from .products import CanonicalProduct
    from .spec_index import CategoryParseStat, ProductSpecRow

NOT_BUILDING: Final = "candidate is not building"
DUPLICATE_PRODUCT: Final = "candidate product duplicate"
INVALID_COVERAGE: Final = "candidate coverage invalid"
MISSING_ATTRIBUTE_PRODUCT: Final = "candidate attribute product missing"


@dataclass(frozen=True, slots=True)
class CandidateAttribute:
    """Bind one ordered attribute to its product for persistence."""

    product_id: str
    attribute: ProductAttribute


@dataclass(frozen=True, slots=True)
class CandidateRows:
    """Validated rows written under one inactive materialization ID."""

    products: tuple[CanonicalProduct, ...]
    attributes: tuple[CandidateAttribute, ...]
    covered_product_ids: tuple[str, ...]
    specs: tuple[ProductSpecRow, ...] = ()
    parse_stats: tuple[CategoryParseStat, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterializationValidationError(Exception):
    """Report a candidate invariant before any row becomes complete."""

    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def publish_candidate(
    database: Path,
    materialization_id: int,
    rows: CandidateRows,
) -> None:
    """Validate all rows, persist atomically, then mark only the candidate complete."""
    try:
        _validate(rows)
    except MaterializationValidationError:
        _mark_failed(database, materialization_id)
        raise
    try:
        _persist_candidate(database, materialization_id, rows)
    except sqlite3.DatabaseError:
        _mark_failed(database, materialization_id)
        raise


def _persist_candidate(
    database: Path,
    materialization_id: int,
    rows: CandidateRows,
) -> None:
    with connect(database) as connection:
        _ = query(connection, "BEGIN IMMEDIATE")
        state = query(
            connection,
            """SELECT attribute_snapshot_id, status
               FROM materialization_snapshots WHERE id = ?""",
            (materialization_id,),
        ).fetchone()
        if state is None or state[1] != "building":
            _ = query(connection, "ROLLBACK")
            raise MaterializationValidationError(NOT_BUILDING)
        attribute_snapshot_id = as_int(state[0])
        for product in rows.products:
            _ = query(
                connection,
                """INSERT INTO products(
                       materialization_id, product_id, category_no,
                       detail_category_no, product_name_raw, product_name_key,
                       active, data_as_of, spec_name, detail, characteristic
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    materialization_id,
                    product.product_id,
                    product.category_key[0],
                    product.category_key[1],
                    product.product_name_raw,
                    product.product_name_key,
                    int(product.active),
                    product.data_as_of,
                    product.spec_name,
                    product.detail,
                    product.characteristic,
                ),
            )
            for offer in product.offers:
                price = _nonnegative_price(offer.contract_price_raw)
                unit_key = normalize_text(offer.unit_raw).derived or None
                _ = query(
                    connection,
                    """INSERT INTO catalog_offers(
                           materialization_id, operation, offer_key, product_id,
                           contract_price_won, unit_raw, unit_key, active,
                           source_updated_at, contract_corp_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        materialization_id,
                        offer.operation.value,
                        offer.offer_key,
                        offer.product_id,
                        price,
                        offer.unit_raw or None,
                        unit_key,
                        int(offer.active),
                        offer.source_updated_at,
                        offer.contract_corp_id or None,
                    ),
                )
        for item in rows.attributes:
            attribute = item.attribute
            _ = query(
                connection,
                """INSERT INTO product_attributes(
                       materialization_id, product_id, attribute_key, ordinal,
                       attribute_snapshot_id, attribute_source_key, raw_name,
                       raw_value, canonical_value, canonical_unit, parse_status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    materialization_id,
                    item.product_id,
                    attribute.attribute_key,
                    attribute.ordinal,
                    attribute_snapshot_id,
                    attribute.attribute_source_key,
                    attribute.raw_name,
                    attribute.raw_value,
                    attribute.canonical_value,
                    attribute.canonical_unit,
                    attribute.parse_status,
                ),
            )
        for item in rows.specs:
            _ = query(
                connection,
                """INSERT INTO product_spec_index(
                       materialization_id,product_id,source_kind,attribute_key,
                       dimension,relation,value_low,value_high,canonical_unit,ordinal
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    materialization_id,
                    item.product_id,
                    item.source_kind,
                    item.attribute_key,
                    item.dimension,
                    item.relation,
                    item.value_low,
                    item.value_high,
                    item.canonical_unit,
                    item.ordinal,
                ),
            )
        for item in rows.parse_stats:
            _ = query(
                connection,
                """INSERT INTO category_parse_stats VALUES(?,?,?,?,?,?,?)""",
                (
                    materialization_id,
                    item.category_no,
                    item.detail_category_no,
                    item.product_count,
                    item.numeric_span_count,
                    item.parsed_semantic_count,
                    item.attribute_covered_count,
                ),
            )
        _ = query(
            connection,
            "UPDATE materialization_snapshots SET status = 'complete' WHERE id = ?",
            (materialization_id,),
        )
        _ = query(connection, "COMMIT")


def _validate(rows: CandidateRows) -> None:
    product_ids = tuple(item.product_id for item in rows.products)
    product_set = frozenset(product_ids)
    if len(product_ids) != len(product_set):
        raise MaterializationValidationError(DUPLICATE_PRODUCT)
    if not frozenset(rows.covered_product_ids).issubset(product_set):
        raise MaterializationValidationError(INVALID_COVERAGE)
    if any(item.product_id not in product_set for item in rows.attributes):
        raise MaterializationValidationError(MISSING_ATTRIBUTE_PRODUCT)
    if any(item.product_id not in product_set for item in rows.specs):
        raise MaterializationValidationError(MISSING_ATTRIBUTE_PRODUCT)


def _mark_failed(database: Path, materialization_id: int) -> None:
    with connect(database) as connection:
        _ = query(
            connection,
            """UPDATE materialization_snapshots SET status = 'failed'
               WHERE id = ? AND status = 'building'""",
            (materialization_id,),
        )


def _nonnegative_price(raw: str) -> int | None:
    candidate = raw.replace(",", "").strip()
    try:
        value = int(candidate)
    except ValueError:
        return None
    return value if value >= 0 else None
