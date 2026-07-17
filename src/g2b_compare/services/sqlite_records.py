"""Project release-pinned SQLite rows into search service records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from g2b_compare.db.sql import SqlParameters, SqlRow, as_int, as_text, query
from g2b_compare.materialize.attributes import ProductAttribute
from g2b_compare.materialize.options import FallbackText, build_option_text
from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.ranking.topk import RankableProduct

from .comparators import CuratedRelation, ObservedOptionRole, ProductRecord
from .search_models import CategoryRef

if TYPE_CHECKING:
    import sqlite3

    from .release_models import ReleaseCandidate, ReleasePin

EMPTY_FALLBACKS: Final = FallbackText("", "", "")


@dataclass(frozen=True, slots=True)
class ProjectionMissingError(Exception):
    """Report a materialization whose persisted projection is incomplete."""

    component: str = "attribute coverage"

    @override
    def __str__(self) -> str:
        return f"SQLite projection missing {self.component}"


@dataclass(frozen=True, slots=True)
class _Offer:
    operation: str
    offer_key: str
    amount_won: int | None
    unit_key: str | None


@dataclass(frozen=True, slots=True)
class _Projection:
    coverage: str
    offers: dict[str, list[_Offer]]
    attributes: dict[str, list[ProductAttribute]]
    roles: dict[str, list[ObservedOptionRole]]
    relations: dict[str, list[CuratedRelation]]


type _OfferMap = dict[str, list[_Offer]]
type _AttributeMap = dict[str, list[ProductAttribute]]
type _RoleMap = dict[str, list[ObservedOptionRole]]
type _RelationMap = dict[str, list[CuratedRelation]]


def load_categories(
    connection: sqlite3.Connection, materialization_id: int
) -> tuple[CategoryRef, ...]:
    """Load distinct active category tuples from one materialization."""
    rows = query(
        connection,
        """SELECT DISTINCT category_no,detail_category_no
           FROM products WHERE materialization_id=? AND active=1
           ORDER BY category_no,detail_category_no""",
        (materialization_id,),
    ).fetchall()
    return tuple(CategoryRef(as_text(row[0]), as_text(row[1])) for row in rows)


def load_product_records(
    connection: sqlite3.Connection,
    release: ReleaseCandidate | ReleasePin,
    product_name_key: str | None = None,
) -> tuple[ProductRecord, ...]:
    """Load active products and all release-pinned ranking provenance."""
    name_parameters = (product_name_key, product_name_key)
    parameters: SqlParameters = (release.materialization_id, *name_parameters)
    products = query(
        connection,
        """SELECT p.product_id,p.category_no,p.detail_category_no,
                   p.product_name_raw,p.product_name_key,p.data_as_of
            FROM products p
            WHERE p.materialization_id=? AND p.active=1
              AND (? IS NULL OR p.product_name_key=?)
            ORDER BY p.product_id""",
        parameters,
    ).fetchall()
    projection = _Projection(
        _coverage(connection, release.materialization_id),
        _offers(connection, parameters),
        _attributes(connection, parameters),
        _roles(connection, parameters),
        _relations(connection, release, product_name_key),
    )
    return tuple(_record(row, projection) for row in products)


def _coverage(connection: sqlite3.Connection, materialization_id: int) -> str:
    row = query(
        connection,
        """SELECT a.complete_product_count,a.active_product_count
           FROM materialization_snapshots m
           JOIN attribute_snapshots a ON a.id=m.attribute_snapshot_id
           WHERE m.id=?""",
        (materialization_id,),
    ).fetchone()
    if row is None:
        raise ProjectionMissingError
    return f"{as_int(row[0])}/{as_int(row[1])}"


def _offers(connection: sqlite3.Connection, parameters: SqlParameters) -> _OfferMap:
    rows = query(
        connection,
        """SELECT o.product_id,o.operation,o.offer_key,
                   o.contract_price_won,o.unit_key
            FROM catalog_offers o
            JOIN products p ON p.materialization_id=o.materialization_id
                           AND p.product_id=o.product_id
            WHERE o.materialization_id=? AND o.active=1 AND p.active=1
              AND (? IS NULL OR p.product_name_key=?)
            ORDER BY o.product_id,o.operation,o.offer_key""",
        parameters,
    ).fetchall()
    grouped: dict[str, list[_Offer]] = {}
    for row in rows:
        grouped.setdefault(as_text(row[0]), []).append(
            _Offer(
                as_text(row[1]), as_text(row[2]),
                None if row[3] is None else as_int(row[3]),
                None if row[4] is None else as_text(row[4]),
            )
        )
    return grouped


def _attributes(
    connection: sqlite3.Connection, parameters: SqlParameters
) -> _AttributeMap:
    rows = query(
        connection,
        """SELECT a.product_id,a.attribute_key,a.ordinal,a.attribute_source_key,
                   a.raw_name,a.raw_value,a.canonical_value,a.canonical_unit,
                   a.parse_status
            FROM product_attributes a
            JOIN products p ON p.materialization_id=a.materialization_id
                           AND p.product_id=a.product_id
            WHERE a.materialization_id=? AND p.active=1
              AND (? IS NULL OR p.product_name_key=?)
            ORDER BY a.product_id,a.attribute_key,a.ordinal,a.attribute_source_key""",
        parameters,
    ).fetchall()
    grouped: dict[str, list[ProductAttribute]] = {}
    for row in rows:
        grouped.setdefault(as_text(row[0]), []).append(
            ProductAttribute(
                as_text(row[1]), as_int(row[2]), as_text(row[3]),
                as_text(row[4]), as_text(row[5]),
                None if row[6] is None else as_text(row[6]),
                None if row[7] is None else as_text(row[7]),
                as_text(row[8]),
            )
        )
    return grouped


def _roles(connection: sqlite3.Connection, parameters: SqlParameters) -> _RoleMap:
    rows = query(
        connection,
        """SELECT r.product_id,r.source_snapshot_id,r.source_row_key,
                   r.delivery_request_key,r.item_sequence,r.change_sequence,
                   r.role_raw,r.observed_at
            FROM option_role_observations r
            JOIN products p ON p.materialization_id=r.materialization_id
                           AND p.product_id=r.product_id
            WHERE r.materialization_id=? AND p.active=1
              AND (? IS NULL OR p.product_name_key=?)
            ORDER BY r.product_id,r.source_snapshot_id,r.source_row_key""",
        parameters,
    ).fetchall()
    grouped: dict[str, list[ObservedOptionRole]] = {}
    for row in rows:
        grouped.setdefault(as_text(row[0]), []).append(
            ObservedOptionRole(
                as_int(row[1]), as_text(row[2]), as_text(row[3]),
                str(as_int(row[4])), str(as_int(row[5])), as_text(row[6]),
                as_text(row[7]),
            )
        )
    return grouped


def _relations(
    connection: sqlite3.Connection,
    release: ReleaseCandidate | ReleasePin,
    product_name_key: str | None,
) -> _RelationMap:
    parameters: SqlParameters = (
        release.materialization_id, release.relation_snapshot_id,
        product_name_key, product_name_key,
    )
    rows = query(
        connection,
        """SELECT p.product_id,r.id,r.parent_id,r.child_id,r.source_type,
                   r.source_sha,r.sheet_name,r.row_no
            FROM curated_relations r
            JOIN products p ON p.materialization_id=?
             AND (p.product_id=r.parent_id OR p.product_id=r.child_id)
            WHERE r.relation_snapshot_id=? AND p.active=1
              AND (? IS NULL OR p.product_name_key=?)
            ORDER BY p.product_id,r.id""",
        parameters,
    ).fetchall()
    grouped: dict[str, list[CuratedRelation]] = {}
    for row in rows:
        grouped.setdefault(as_text(row[0]), []).append(
            CuratedRelation(
                as_text(row[1]), as_text(row[2]), as_text(row[3]),
                as_text(row[4]), as_text(row[5]), as_text(row[6]), as_int(row[7]),
            )
        )
    return grouped


def _record(row: SqlRow, projection: _Projection) -> ProductRecord:
    product_id = as_text(row[0])
    option_text = build_option_text(
        tuple(projection.attributes.get(product_id, [])), EMPTY_FALLBACKS
    ).text
    rankable = RankableProduct(
        product_id=product_id,
        category_key=(as_text(row[1]), as_text(row[2])),
        product_name_key=as_text(row[4]),
        option_text=option_text,
        active=True,
        price=_price(tuple(projection.offers.get(product_id, []))),
    )
    return ProductRecord(
        rankable,
        as_text(row[3]),
        as_text(row[5]),
        projection.coverage,
        tuple(projection.roles.get(product_id, [])),
        tuple(projection.relations.get(product_id, [])),
    )


def _price(offers: tuple[_Offer, ...]) -> ComparisonPrice:
    if not offers:
        return _inactive_price("no-active-offer")
    valid: list[_Offer] = []
    for offer in offers:
        if offer.amount_won is None:
            return _inactive_price("missing-price")
        if offer.amount_won == 0:
            return _inactive_price("zero-price")
        if offer.unit_key is None:
            return _inactive_price("missing-unit")
        valid.append(offer)
    if len({item.unit_key for item in valid}) != 1:
        return _inactive_price("mixed-unit")
    selected = min(
        valid,
        key=lambda item: (item.amount_won or 0, item.operation, item.offer_key),
    )
    return ComparisonPrice(
        active=True,
        amount_won=selected.amount_won,
        unit_key=selected.unit_key,
        offer_key=(selected.operation, selected.offer_key),
        reason=None,
    )


def _inactive_price(reason: str) -> ComparisonPrice:
    return ComparisonPrice(
        active=False, amount_won=None, unit_key=None, offer_key=None, reason=reason
    )
