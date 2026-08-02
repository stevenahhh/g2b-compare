"""Rank compatible main-product comparison candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from g2b_compare.db.sql import SqlValue, as_int, as_text, query

from .estimate_features import (
    line_component as _line_component,
)
from .estimate_features import (
    product_features as _product_features,
)
from .estimate_models import (
    COMPARISON_SLOT_COUNT,
    ComparisonView,
)
from .estimate_models import (
    MainCandidate as _MainCandidate,
)
from .estimate_text import (
    cable_signature as _cable_signature,
)
from .estimate_text import (
    number_key as _number_key,
)

if TYPE_CHECKING:
    import sqlite3

    from g2b_compare.services import EstimateLine


def rank_main_candidates(  # noqa: C901, PLR0912, PLR0915
    connection: sqlite3.Connection,
    line: EstimateLine,
    option_lines: tuple[EstimateLine, ...],
) -> tuple[_MainCandidate, ...]:
    """Rank deterministic compatible alternatives for one main line."""
    anchor = query(
        connection,
        """
        SELECT spec, raw_json, category_number FROM priority_products
        WHERE product_id = ?
        """,
        (line.product_id,),
    ).fetchone()
    if anchor is None:
        return ()
    anchor_core, anchor_components = _product_features(
        as_text(anchor[0]), as_text(anchor[1])
    )
    allowed_components = set(anchor_components)
    allowed_components.update(
        component
        for item in option_lines
        if (component := _line_component(item)) is not None
    )
    candidate_sql = """
        SELECT product.product_id, product.company_name, product.spec,
        product.price_won, product.raw_json,
        COALESCE(company.source_row, 2147483647)
        FROM priority_products AS product
        LEFT JOIN priority_companies AS company
        ON company.name = product.company_name
        WHERE product.category_number = ?
    """
    parameters: list[SqlValue] = [as_text(anchor[2])]
    filters: list[str] = []
    anchor_spec = as_text(anchor[0])
    if "," in anchor_spec:
        filters.append(" AND product.spec LIKE ?")
        parameters.append(f"%{anchor_spec.rsplit(',', 1)[-1].strip()}")
    for feature in sorted(anchor_core):
        feature_type, _, value = feature.partition(":")
        if feature_type == "resolution":
            megapixels = _number_key(str(float(value) * 100))
            filters.append(
                """
                 AND (lower(product.raw_json) LIKE ?
                 OR product.raw_json LIKE ? OR product.raw_json LIKE ?)
                """
            )
            parameters.extend(
                (f"%{value}mp/%", f"%{megapixels}만화소%", f"%{value}메가픽셀%")
            )
        elif feature_type == "zoom":
            filters.append(
                """
                 AND (lower(product.raw_json) LIKE ?
                 OR lower(product.raw_json) LIKE ? OR product.raw_json LIKE ?)
                """
            )
            parameters.extend((f"%x{value}/%", f"%x{value}배%", f"%{value}배줌%"))
        elif feature_type == "sensor":
            filters.append(" AND lower(product.raw_json) LIKE ?")
            parameters.append(f"%{value}mmcmos%")
        elif feature_type == "special":
            filters.append(" AND product.raw_json LIKE ?")
            parameters.append(f"%{value}%")
    rows = query(
        connection,
        candidate_sql + "".join(filters),
        tuple(parameters),
    ).fetchall()
    if len({as_text(row[1]) for row in rows}) < COMPARISON_SLOT_COUNT:
        rows = query(connection, candidate_sql, tuple(parameters[:1])).fetchall()
    cable_signature = _cable_signature(line.item_name_snapshot, line.spec_snapshot)
    by_identity: dict[tuple[str, str], _MainCandidate] = {}
    for row in rows:
        product_id = as_text(row[0])
        company = as_text(row[1])
        spec = as_text(row[2])
        price = as_int(row[3])
        if (
            cable_signature is not None
            and _cable_signature(line.item_name_snapshot, spec) != cable_signature
        ):
            continue
        core, components = _product_features(spec, as_text(row[4]))
        key = (
            len(anchor_core - core),
            0,
            len(components - allowed_components),
            -len(components & allowed_components),
            len(components - anchor_components),
            int(price < line.unit_price_won_snapshot),
            abs(price - line.unit_price_won_snapshot),
            product_id,
        )
        candidate = _MainCandidate(
            ComparisonView("", product_id, None, company, spec, price),
            as_int(row[5]),
            key,
        )
        identity = (product_id, company)
        current = by_identity.get(identity)
        if current is None or candidate.key < current.key:
            by_identity[identity] = candidate
    if filters:
        fallback_sql = candidate_sql.replace("product.raw_json", "''")
        for row in query(
            connection,
            fallback_sql,
            tuple(parameters[:1]),
        ).fetchall():
            product_id = as_text(row[0])
            company = as_text(row[1])
            candidate = _MainCandidate(
                ComparisonView(
                    "",
                    product_id,
                    None,
                    company,
                    as_text(row[2]),
                    as_int(row[3]),
                ),
                as_int(row[5]),
                (
                    1_000_000,
                    1_000_000,
                    1_000_000,
                    0,
                    1_000_000,
                    int(as_int(row[3]) < line.unit_price_won_snapshot),
                    abs(as_int(row[3]) - line.unit_price_won_snapshot),
                    product_id,
                ),
            )
            identity = (product_id, company)
            current = by_identity.get(identity)
            if current is None or candidate.key < current.key:
                by_identity[identity] = candidate
    return tuple(sorted(by_identity.values(), key=lambda item: item.key))
