"""Frozen release SQLite projection for strict E0 export."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING

from g2b_compare.db.sql import SqlValue, as_int, as_text, query

from .e0_models import (
    E0ExportBlocked,
    E0Product,
    FrozenE0Release,
    ParserFieldKind,
    ParserSource,
    ReleaseIdentity,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services.release_models import ReleasePin


def read_frozen_e0_release(
    connection: sqlite3.Connection, pin: ReleasePin
) -> FrozenE0Release:
    """Project one already-pinned query-only transaction into E0 input."""
    identity = _identity(connection, pin)
    prices = _prices(connection, pin.materialization_id)
    rows = query(
        connection,
        """SELECT p.product_id,p.category_no,p.detail_category_no,
                  p.product_name_key,s.option_text,p.active,s.active,COUNT(a.attribute_key)
           FROM products p
           JOIN search_membership s
             ON s.materialization_id=p.materialization_id AND s.product_id=p.product_id
           LEFT JOIN product_attributes a
             ON a.materialization_id=p.materialization_id AND a.product_id=p.product_id
           WHERE p.materialization_id=?
           GROUP BY p.product_id,p.category_no,p.detail_category_no,
                    p.product_name_key,s.option_text,p.active,s.active
           ORDER BY p.product_id""",
        (pin.materialization_id,),
    ).fetchall()
    active_count_row = query(
        connection,
        "SELECT COUNT(*) FROM products WHERE materialization_id=? AND active=1",
        (pin.materialization_id,),
    ).fetchone()
    if active_count_row is None:
        detail = "frozen release products missing"
        raise E0ExportBlocked(detail)
    products = tuple(_product(row, prices) for row in rows)
    if sum(product.active for product in products) != as_int(active_count_row[0]):
        detail = "frozen release search membership drift"
        raise E0ExportBlocked(detail)
    sources = (*_attribute_sources(connection, pin), *_fallback_sources(products))
    return FrozenE0Release(identity, products, sources)


def _identity(connection: sqlite3.Connection, pin: ReleasePin) -> ReleaseIdentity:
    row = query(
        connection,
        "SELECT release_bundle_sha,created_at FROM release_bundles WHERE id=?",
        (pin.bundle_id,),
    ).fetchone()
    if row is None:
        detail = "frozen release bundle missing"
        raise E0ExportBlocked(detail)
    members = query(
        connection,
        """SELECT member_name,member_bytes FROM search_index_members
           WHERE materialization_id=? AND member_name IN (?,?) ORDER BY member_name""",
        (pin.materialization_id, "char-idf.f64le", "word-idf.f64le"),
    ).fetchall()
    digests = {
        as_text(item[0]): hashlib.sha256(_bytes(item[1])).hexdigest()
        for item in members
    }
    if set(digests) != {"char-idf.f64le", "word-idf.f64le"}:
        detail = "frozen release IDF members missing"
        raise E0ExportBlocked(detail)
    return ReleaseIdentity(
        bundle_id=pin.bundle_id,
        release_bundle_sha=as_text(row[0]),
        materialization_id=pin.materialization_id,
        materialization_sha=pin.materialization_source_sha,
        index_artifact_sha=pin.index_artifact_sha,
        index_manifest_sha=pin.index_manifest_sha,
        word_idf_sha=digests["word-idf.f64le"],
        char_idf_sha=digests["char-idf.f64le"],
        relation_snapshot_sha=pin.relation_content_sha,
        ranking_version=pin.ranking_version,
        created_at_utc=as_text(row[1]),
    )


def _prices(
    connection: sqlite3.Connection, materialization_id: int
) -> dict[str, tuple[int | None, str | None]]:
    rows = query(
        connection,
        """SELECT product_id,contract_price_won,unit_key
           FROM catalog_offers WHERE materialization_id=? AND active=1
           ORDER BY product_id,operation,offer_key""",
        (materialization_id,),
    ).fetchall()
    grouped: defaultdict[str, list[tuple[int | None, str | None]]] = defaultdict(list)
    for row in rows:
        grouped[as_text(row[0])].append((_optional_int(row[1]), _optional_text(row[2])))
    output: dict[str, tuple[int | None, str | None]] = {}
    for product_id, offers in grouped.items():
        units = {unit for _, unit in offers if unit is not None}
        valid = all(
            price is not None and price > 0 and unit is not None
            for price, unit in offers
        )
        if valid and len(units) == 1:
            output[product_id] = (
                min(price for price, _ in offers if price is not None),
                next(iter(units)),
            )
        else:
            output[product_id] = None, None
    return output


def _product(
    row: tuple[SqlValue, ...], prices: dict[str, tuple[int | None, str | None]]
) -> E0Product:
    product_id = as_text(row[0])
    price, unit = prices.get(product_id, (None, None))
    product_active = bool(as_int(row[5]))
    search_active = bool(as_int(row[6]))
    if product_active != search_active:
        detail = f"product {product_id} active lane drift"
        raise E0ExportBlocked(detail)
    return E0Product(
        product_id,
        as_text(row[1]),
        as_text(row[2]),
        as_text(row[3]),
        as_text(row[4]),
        product_active,
        as_int(row[7]),
        price,
        unit,
    )


def _attribute_sources(
    connection: sqlite3.Connection, pin: ReleasePin
) -> tuple[ParserSource, ...]:
    rows = query(
        connection,
        """SELECT a.product_id,a.attribute_source_key,a.ordinal,a.raw_value
           FROM product_attributes a JOIN products p
             ON p.materialization_id=a.materialization_id
            AND p.product_id=a.product_id
           WHERE a.materialization_id=? AND p.active=1
           ORDER BY a.product_id,a.attribute_source_key,a.ordinal""",
        (pin.materialization_id,),
    ).fetchall()
    return tuple(
        ParserSource(
            as_text(row[0]),
            "raw_value",
            as_text(row[1]),
            as_int(row[2]),
            as_text(row[3]),
        )
        for row in rows
        if as_text(row[3])
    )


def _fallback_sources(products: tuple[E0Product, ...]) -> tuple[ParserSource, ...]:
    output: list[ParserSource] = []
    for product in products:
        if not product.active:
            continue
        for ordinal, segment in enumerate(product.option_text.split(" | ")):
            prefix, separator, text = segment.partition(":")
            kind = _fallback_kind(prefix)
            if separator and kind is not None and text:
                output.append(
                    ParserSource(
                        product.product_id,
                        kind,
                        f"search-membership:{product.product_id}",
                        ordinal,
                        text,
                    )
                )
    return tuple(output)


def _fallback_kind(prefix: str) -> ParserFieldKind | None:
    kinds: dict[str, ParserFieldKind] = {
        "spec": "spec_name",
        "detail": "detail",
        "characteristic": "characteristic",
    }
    return kinds.get(prefix)


def _bytes(value: SqlValue) -> bytes:
    if not isinstance(value, bytes):
        detail = "frozen release index member is not bytes"
        raise E0ExportBlocked(detail)
    return value


def _optional_int(value: SqlValue) -> int | None:
    return None if value is None else as_int(value)


def _optional_text(value: SqlValue) -> str | None:
    return None if value is None else as_text(value)
