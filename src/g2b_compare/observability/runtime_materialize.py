"""Build a persisted materialization from the latest complete runtime sources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.redact import JsonScalar
from g2b_compare.db.connection import connect
from g2b_compare.db.materialization import MaterializationRepository
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.materialize.attributes import (
    AttributeSourceRow,
    materialize_attributes,
)
from g2b_compare.materialize.products import SourceOffer, merge_products
from g2b_compare.materialize.repository import (
    CandidateAttribute,
    CandidateRows,
    publish_candidate,
)
from g2b_compare.materialize.spec_index import build_spec_projection
from g2b_compare.observability.runtime_ops import RuntimeOperationError

if TYPE_CHECKING:
    from pathlib import Path

RAW_FIELDS: Final = TypeAdapter(dict[str, JsonScalar])
OFFER_OPERATIONS: Final = tuple(Operation)[:3]
COMPLETE_STATES: Final = (
    "complete-nonempty",
    "complete-empty",
    "carried-forward",
)
OPTION_ROLES: Final = frozenset({"선택사양(별도구매)", "동시구매"})
MATERIALIZATION_SOURCE_MISSING: Final = "materialization-source-missing"
ATTRIBUTE_SNAPSHOT_INCOMPLETE: Final = "attribute-snapshot-incomplete"


def materialize(database: Path) -> int:
    """Publish the latest complete catalog and attribute tuple as a candidate."""
    catalog_id, attribute_id = _latest_complete_tuple(database)
    repository = MaterializationRepository(database)
    materialization_id = repository.create(
        catalog_id,
        attribute_id,
        ("v2", "v1"),
    )
    with connect(database) as connection:
        state = query(
            connection,
            "SELECT status FROM materialization_snapshots WHERE id=?",
            (materialization_id,),
        ).fetchone()
    if state is not None and as_text(state[0]) == "complete":
        return materialization_id
    products = merge_products(_offers(database), ())
    attributes, covered = _attributes(database, attribute_id)
    specs, stats = build_spec_projection(
        products,
        attributes,
        covered,
        _option_specs(database),
    )
    publish_candidate(
        database,
        materialization_id,
        CandidateRows(products, attributes, covered, specs, stats),
    )
    return materialization_id


def _latest_complete_tuple(database: Path) -> tuple[int, int]:
    with connect(database) as connection:
        row = query(
            connection,
            """SELECT catalogs.id,attributes.id,attributes.active_product_count,
                      COUNT(states.product_id),
                      SUM(CASE WHEN states.fetch_status IN (?,?,?) THEN 1 ELSE 0 END)
               FROM catalog_generations AS catalogs
               JOIN active_attribute_snapshots AS active
                 ON active.catalog_generation_id=catalogs.id
               JOIN attribute_snapshots AS attributes
                 ON attributes.id=active.snapshot_id
               LEFT JOIN attribute_product_states AS states
                 ON states.attribute_snapshot_id=attributes.id
               WHERE attributes.status='complete'
               GROUP BY catalogs.id,attributes.id
               ORDER BY catalogs.id DESC LIMIT 1""",
            COMPLETE_STATES,
        ).fetchone()
    if row is None:
        raise RuntimeOperationError(MATERIALIZATION_SOURCE_MISSING)
    active_count = as_int(row[2])
    state_count = as_int(row[3])
    complete_count = 0 if row[4] is None else as_int(row[4])
    if state_count != active_count or complete_count != active_count:
        raise RuntimeOperationError(ATTRIBUTE_SNAPSHOT_INCOMPLETE)
    return as_int(row[0]), as_int(row[1])


def _offers(database: Path) -> tuple[SourceOffer, ...]:
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT records.operation,records.source_record_key,
                      records.product_id,records.raw_fields_json
               FROM active_source_snapshots AS active
               JOIN source_records AS records
                 ON records.source_snapshot_id=active.snapshot_id
                AND records.operation=active.operation
               WHERE records.is_tombstone=0
                 AND records.operation IN (?,?,?)
               ORDER BY records.operation,records.source_record_key""",
            tuple(item.value for item in OFFER_OPERATIONS),
        ).fetchall()
    observed_at = datetime.now(UTC).isoformat()
    return tuple(
        _offer(
            Operation(as_text(row[0])),
            as_text(row[1]),
            as_text(row[2]),
            RAW_FIELDS.validate_json(as_text(row[3])),
            observed_at,
        )
        for row in rows
    )


def _offer(
    operation: Operation,
    source_key: str,
    product_id: str,
    raw: dict[str, JsonScalar],
    observed_at: str,
) -> SourceOffer:
    return SourceOffer(
        operation=operation,
        offer_key=source_key,
        product_id=product_id,
        category_no=_text(raw, "prdctClsfcNo"),
        detail_category_no=_text(raw, "dtilPrdctClsfcNo"),
        product_name_raw=_first(
            raw,
            "prdctIdntNoNm",
            "prdctNm",
            "prdctClsfcNoNm",
        ),
        spec_name=_text(raw, "prdctSpecNm"),
        detail=_text(raw, "prdctDtlInfo"),
        characteristic=_text(raw, "prodctChrInfoIntrcn"),
        contract_price_raw=_text(raw, "cntrctPrceAmt"),
        unit_raw=_text(raw, "prdctUnit"),
        product_unit_price_raw=_text(raw, "orderCalclPrceAmt"),
        active=True,
        source_updated_at=_first(raw, "chgDt", "rgstDt") or observed_at,
        raw_fields_json=RAW_FIELDS.dump_json(raw).decode(),
        contract_corp_id=_first(raw, "cntrctCorpNo", "cntrctCorpBizno"),
    )


def _attributes(
    database: Path,
    attribute_id: int,
) -> tuple[tuple[CandidateAttribute, ...], tuple[str, ...]]:
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT product_id,attribute_source_key,raw_fields_json
               FROM attribute_records WHERE attribute_snapshot_id=?
               ORDER BY product_id,attribute_source_key""",
            (attribute_id,),
        ).fetchall()
        covered_rows = query(
            connection,
            """SELECT product_id FROM attribute_product_states
               WHERE attribute_snapshot_id=? AND fetch_status IN (?,?,?)
               ORDER BY product_id""",
            (attribute_id, *COMPLETE_STATES),
        ).fetchall()
    grouped: dict[str, list[AttributeSourceRow]] = {}
    for row in rows:
        product_id = as_text(row[0])
        source_key = as_text(row[1])
        raw = RAW_FIELDS.validate_json(as_text(row[2]))
        name = _text(raw, "attrNm") or source_key
        ordinal_value = raw.get("source_ordinal", 0)
        ordinal = ordinal_value if isinstance(ordinal_value, int) else 0
        grouped.setdefault(product_id, []).append(
            AttributeSourceRow(
                name,
                ordinal,
                source_key,
                name,
                _text(raw, "attrVal"),
                _text(raw, "attrVal") or None,
                _text(raw, "attrUnit") or None,
                "raw",
            )
        )
    attributes = tuple(
        CandidateAttribute(product_id, attribute)
        for product_id in sorted(grouped)
        for attribute in materialize_attributes(tuple(grouped[product_id]))
    )
    return attributes, tuple(as_text(row[0]) for row in covered_rows)


def _option_specs(database: Path) -> tuple[tuple[str, str], ...]:
    with connect(database) as connection:
        rows = query(
            connection,
            """SELECT records.product_id,records.raw_fields_json
               FROM active_source_snapshots AS active
               JOIN source_records AS records
                 ON records.source_snapshot_id=active.snapshot_id
                AND records.operation=active.operation
               WHERE records.operation=? AND records.is_tombstone=0
               ORDER BY records.source_record_key""",
            (Operation.GET_DELIVERY_REQUEST_DETAIL.value,),
        ).fetchall()
    result: list[tuple[str, str]] = []
    for row in rows:
        raw = RAW_FIELDS.validate_json(as_text(row[1]))
        if _text(raw, "optnDivCdNm") not in OPTION_ROLES:
            continue
        text = _first(raw, "prdctIdntNoNm", "prdctSpecNm")
        if text:
            result.append((as_text(row[0]), text))
    return tuple(result)


def _first(raw: dict[str, JsonScalar], *keys: str) -> str:
    return next((value for key in keys if (value := _text(raw, key))), "")


def _text(raw: dict[str, JsonScalar], key: str) -> str:
    value = raw.get(key)
    return "" if value is None else str(value).strip()
