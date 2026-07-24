"""Resolve catalog selections and estimate comparison candidates."""
# Selection and comparison matching share one transactional unit.

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final

from fastapi import HTTPException

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import SqlRow, SqlValue, as_int, as_text, query
from g2b_compare.priority_attributes import parse_product_attributes
from g2b_compare.services import EstimateLine, EstimateLineInput

if TYPE_CHECKING:
    import sqlite3
    from decimal import Decimal
    from pathlib import Path

    from g2b_compare.priority_models import ProductAttribute
    from g2b_compare.services import EstimateDraft

COMPARISON_SLOT_COUNT: Final = 3
RELATION_REQUIRED_DETAIL: Final = (
    "\uac80\uc99d\ub41c \ubcf8\ud488/\uc635\uc158 \uad00\uacc4\uac00 \ud544\uc694\ud568"
)
ALTERNATIVE_COUNT: Final = COMPARISON_SLOT_COUNT - 1
PRICE_LADDER_PERCENTAGES: Final = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110)
KOREANET_COMPANY: Final = "주식회사 코리아넷"


@dataclass(frozen=True, slots=True)
class ComparisonView:
    """One comparison candidate shown in the estimate editor."""

    slot: str
    product_id: str
    relation_id: str | None
    company: str
    spec: str
    price_won: int
    attributes: tuple[ProductAttribute, ...] = ()
    detail_url: str = ""


@dataclass(frozen=True, slots=True)
class _MainCandidate:
    view: ComparisonView
    source_row: int
    key: tuple[int, int, int, int, int, int, int, str]


@dataclass(frozen=True, slots=True)
class _OptionCandidate:
    view: ComparisonView
    item_name: str
    match_text: str


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
                raise HTTPException(
                    status_code=400,
                    detail=RELATION_REQUIRED_DETAIL,
                )
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
            raise HTTPException(
                status_code=400,
                detail=RELATION_REQUIRED_DETAIL,
            )
        return _main_input(product_id, quantity, product)


def seed_comparisons(database: Path, line: EstimateLine) -> None:
    """Pin the selection and two compatible alternatives as A/B/C."""
    with connect(database) as connection:
        seed_comparisons_in_transaction(connection, line)


def seed_document_comparisons_in_transaction(
    connection: sqlite3.Connection,
    lines: tuple[EstimateLine, ...],
) -> None:
    """Seed all comparisons after the full document has been inserted."""
    missing_ids = {line.id for line in lines if not _has_comparisons(connection, line)}
    if not missing_ids:
        return
    for line_id in missing_ids:
        _ = query(
            connection,
            "DELETE FROM estimate_comparisons WHERE estimate_line_id = ?",
            (line_id,),
        )
    contexts: dict[
        str, tuple[tuple[_MainCandidate, ...], tuple[_MainCandidate, ...]]
    ] = {}
    for line in lines:
        if line.line_kind != "main":
            continue
        options = tuple(
            item
            for item in lines
            if item.line_kind == "option" and item.parent_product_id == line.product_id
        )
        ranked = _rank_main_candidates(connection, line, options)
        baseline = _koreanet_main(ranked)
        chosen = _choose_main_alternatives(
            ranked,
            baseline,
            distinct_product_ids=_requires_distinct_product_ids(connection, line),
        )
        candidates = (
            () if baseline is None else (baseline.view, *(item.view for item in chosen))
        )
        if line.id in missing_ids:
            _insert_comparisons(connection, line, candidates)
        contexts[line.product_id] = (ranked, chosen)
    for line in lines:
        if line.line_kind != "option":
            continue
        ranked, chosen = contexts.get(line.parent_product_id or "", ((), ()))
        alternatives = (
            _option_alternatives(connection, line, ranked, chosen)
            if ranked or chosen
            else _standalone_option_alternatives(connection, line)
        )
        if line.id in missing_ids:
            _insert_comparisons(connection, line, alternatives)


def seed_comparisons_in_transaction(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> None:
    """Seed one line for legacy form routes."""
    if _has_comparisons(connection, line):
        return
    _ = query(
        connection,
        "DELETE FROM estimate_comparisons WHERE estimate_line_id = ?",
        (line.id,),
    )
    if line.line_kind == "main":
        ranked = _rank_main_candidates(connection, line, ())
        baseline = _koreanet_main(ranked)
        chosen = _choose_main_alternatives(
            ranked,
            baseline,
            distinct_product_ids=_requires_distinct_product_ids(connection, line),
        )
        alternatives = (
            () if baseline is None else (baseline.view, *(item.view for item in chosen))
        )
    else:
        chosen = _stored_parent_alternatives(connection, line)
        alternatives = (
            _option_alternatives(connection, line, chosen, chosen)
            if chosen
            else _standalone_option_alternatives(connection, line)
        )
    _insert_comparisons(connection, line, alternatives)


def _standalone_option_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[ComparisonView, ...]:
    parent = query(
        connection,
        """
        SELECT category_name, spec, company_name, unit, price_won
        FROM priority_products WHERE product_id = ?
        """,
        (line.parent_product_id,),
    ).fetchone()
    if parent is None or line.parent_product_id is None:
        return ()
    parent_line = EstimateLine(
        line.id,
        line.line_no,
        "main",
        line.parent_product_id,
        None,
        None,
        None,
        None,
        as_text(parent[0]),
        as_text(parent[1]),
        as_text(parent[2]),
        as_text(parent[3]),
        as_int(parent[4]),
        line.quantity,
    )
    ranked = _rank_main_candidates(connection, parent_line, (line,))
    chosen = _choose_main_alternatives(ranked, _koreanet_main(ranked))
    return _option_alternatives(connection, line, ranked, chosen)


def comparison_views(
    database: Path,
    draft: EstimateDraft,
) -> dict[str, tuple[ComparisonView, ...]]:
    """Return ordered comparison snapshots for every visible line."""
    result: dict[str, tuple[ComparisonView, ...]] = {}
    with connect(database) as connection:
        for line in draft.lines:
            rows = query(
                connection,
                """
                SELECT comparison.slot, comparison.product_id,
                comparison.relation_id, comparison.company_snapshot,
                comparison.spec_snapshot, comparison.price_won_snapshot,
                COALESCE(product.raw_json, parent.raw_json),
                COALESCE(
                    NULLIF(relation.detail_url, ''),
                    NULLIF(product.detail_url, ''),
                    parent.detail_url,
                    ''
                )
                FROM estimate_comparisons AS comparison
                LEFT JOIN priority_products AS product
                ON product.product_id = comparison.product_id
                LEFT JOIN priority_products AS parent
                ON parent.product_id = ?
                LEFT JOIN verified_product_options AS relation
                ON relation.relation_id = comparison.relation_id
                WHERE estimate_line_id = ? ORDER BY slot
                """,
                (line.parent_product_id, line.id),
            ).fetchall()
            result[line.id] = tuple(
                ComparisonView(
                    as_text(row[0]),
                    as_text(row[1]),
                    None if row[2] is None else as_text(row[2]),
                    as_text(row[3]),
                    as_text(row[4]),
                    as_int(row[5]),
                    parse_product_attributes(_text_or(row[6], "{}")),
                    as_text(row[7]),
                )
                for row in rows
            )
    return result


def _rank_main_candidates(  # noqa: C901, PLR0912, PLR0915
    connection: sqlite3.Connection,
    line: EstimateLine,
    option_lines: tuple[EstimateLine, ...],
) -> tuple[_MainCandidate, ...]:
    anchor = query(
        connection,
        "SELECT spec, raw_json, category_number FROM priority_products "
        "WHERE product_id = ?",
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
                " AND (lower(product.raw_json) LIKE ?"
                " OR product.raw_json LIKE ? OR product.raw_json LIKE ?)"
            )
            parameters.extend(
                (
                    f"%{value}mp/%",
                    f"%{megapixels}\ub9cc\ud654\uc18c%",
                    f"%{value}\uba54\uac00\ud53d\uc140%",
                )
            )
        elif feature_type == "zoom":
            filters.append(
                " AND (lower(product.raw_json) LIKE ?"
                " OR lower(product.raw_json) LIKE ? OR product.raw_json LIKE ?)"
            )
            parameters.extend(
                (f"%x{value}/%", f"%x{value}\ubc30%", f"%{value}\ubc30\uc90c%")
            )
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
    by_company: dict[str, _MainCandidate] = {}
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
            len(core - anchor_core),
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
        current = by_company.get(company)
        if current is None or candidate.key < current.key:
            by_company[company] = candidate
    if filters:
        fallback_sql = candidate_sql.replace("product.raw_json", "''")
        for row in query(
            connection,
            fallback_sql,
            tuple(parameters[:1]),
        ).fetchall():
            product_id = as_text(row[0])
            company = as_text(row[1])
            spec = as_text(row[2])
            price = as_int(row[3])
            candidate = _MainCandidate(
                ComparisonView("", product_id, None, company, spec, price),
                as_int(row[5]),
                (
                    1_000_000,
                    1_000_000,
                    1_000_000,
                    0,
                    1_000_000,
                    int(price < line.unit_price_won_snapshot),
                    abs(price - line.unit_price_won_snapshot),
                    product_id,
                ),
            )
            current = by_company.get(company)
            if current is None or candidate.key < current.key:
                by_company[company] = candidate
    return tuple(sorted(by_company.values(), key=lambda item: item.key))


def _choose_main_alternatives(  # noqa: C901
    ranked: tuple[_MainCandidate, ...],
    baseline: _MainCandidate | None,
    *,
    distinct_product_ids: bool = False,
) -> tuple[_MainCandidate, ...]:
    if baseline is None:
        return ()
    eligible = tuple(
        item
        for item in ranked
        if item.view.company != KOREANET_COMPANY
        and item.view.price_won >= baseline.view.price_won
    )
    if not eligible:
        return ()
    best_compatibility = eligible[0].key[:5]
    preferred = tuple(item for item in eligible if item.key[:5] == best_compatibility)
    chosen: list[_MainCandidate] = []
    companies = {KOREANET_COMPANY}
    product_ids = {baseline.view.product_id}

    def choose(item: _MainCandidate, percentage: int | None) -> None:
        if item.view.company in companies:
            return
        if distinct_product_ids and item.view.product_id in product_ids:
            return
        if percentage is not None and not _within_price_limit(
            baseline.view.price_won, item.view.price_won, percentage
        ):
            return
        chosen.append(item)
        companies.add(item.view.company)
        product_ids.add(item.view.product_id)

    for percentage in PRICE_LADDER_PERCENTAGES:
        for item in preferred:
            choose(item, percentage)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
        if len(chosen) == ALTERNATIVE_COUNT:
            break
    if len(chosen) < ALTERNATIVE_COUNT:
        for item in preferred:
            choose(item, None)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
    if len(chosen) < ALTERNATIVE_COUNT:
        for item in eligible:
            choose(item, None)
            if len(chosen) == ALTERNATIVE_COUNT:
                break
    return tuple(
        sorted(
            chosen,
            key=lambda item: (
                item.source_row,
                item.view.company.encode("utf-8"),
                item.view.product_id,
            ),
        )
    )


def _koreanet_main(
    ranked: tuple[_MainCandidate, ...],
) -> _MainCandidate | None:
    return next(
        (item for item in ranked if item.view.company == KOREANET_COMPANY),
        None,
    )


def _option_alternatives(  # noqa: C901, PLR0912
    connection: sqlite3.Connection,
    line: EstimateLine,
    ranked_mains: tuple[_MainCandidate, ...],
    chosen_mains: tuple[_MainCandidate, ...],
) -> tuple[ComparisonView, ...]:
    reserved_companies = {item.view.company for item in chosen_mains}
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    alternatives: list[ComparisonView] = []
    companies = {line.company_snapshot}
    used_product_ids: set[str] = {line.product_id} if requires_distinct_ids else set()
    for item in _same_option_relation_alternatives(connection, line):
        if item.company in companies or (
            requires_distinct_ids and item.product_id in used_product_ids
        ):
            continue
        alternatives.append(item)
        companies.add(item.company)
        if requires_distinct_ids:
            used_product_ids.add(item.product_id)
    if len(alternatives) == ALTERNATIVE_COUNT:
        return tuple(alternatives)
    for allow_expensive in (False, True):
        for preferred in chosen_mains or ranked_mains:
            candidate = _best_option_for_main(
                connection,
                line,
                preferred,
                used_product_ids,
                fallback=False,
                allow_expensive=allow_expensive,
            )
            if candidate is None:
                for fallback in ranked_mains:
                    if (
                        fallback.view.company in reserved_companies
                        or fallback.view.company in companies
                    ):
                        continue
                    candidate = _best_option_for_main(
                        connection,
                        line,
                        fallback,
                        used_product_ids,
                        fallback=True,
                        allow_expensive=allow_expensive,
                    )
                    if candidate is not None:
                        break
            if candidate is None or candidate.company in companies:
                continue
            alternatives.append(candidate)
            companies.add(candidate.company)
            if requires_distinct_ids:
                used_product_ids.add(candidate.product_id)
            if len(alternatives) == ALTERNATIVE_COUNT:
                break
        if len(alternatives) == ALTERNATIVE_COUNT:
            break
    return tuple(alternatives)


def _same_option_relation_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[ComparisonView, ...]:
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


def _best_option_for_main(  # noqa: PLR0913
    connection: sqlite3.Connection,
    line: EstimateLine,
    main: _MainCandidate,
    used_product_ids: set[str],
    *,
    fallback: bool,
    allow_expensive: bool = False,
) -> ComparisonView | None:
    candidates = _group_option_candidates(connection, main.view.product_id)
    if not candidates:
        candidates = _company_option_candidates(connection, main.view.company)
    kind = _line_component(line)
    if kind is None:
        return None
    requirements = _option_requirements(kind, line.spec_snapshot)
    compatible: list[tuple[tuple[int, int, int, int, str], ComparisonView]] = []
    for candidate in candidates:
        if _canonical_component(candidate.item_name) != kind:
            continue
        if not _option_matches(line, candidate, kind, requirements):
            continue
        price = candidate.view.price_won
        if price < line.unit_price_won_snapshot:
            continue
        if not allow_expensive and not _within_price_limit(
            line.unit_price_won_snapshot, price, 110
        ):
            continue
        if candidate.view.product_id in used_product_ids:
            continue
        identity_penalty = int(
            candidate.view.product_id == line.product_id
            if fallback
            else candidate.view.product_id != line.product_id
        )
        similarity_penalty = 0
        if kind == "hdd":
            similarity_penalty = -int(
                SequenceMatcher(
                    None,
                    _normalize(line.spec_snapshot),
                    _normalize(candidate.match_text),
                ).ratio()
                * 1000
            )
        key = (
            0,
            identity_penalty,
            similarity_penalty,
            price - line.unit_price_won_snapshot,
            candidate.view.product_id,
        )
        compatible.append((key, candidate.view))
    return min(compatible, default=((), None), key=lambda item: item[0])[1]


def _group_option_candidates(
    connection: sqlite3.Connection,
    main_product_id: str,
) -> tuple[_OptionCandidate, ...]:
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


def _company_option_candidates(
    connection: sqlite3.Connection,
    company: str,
) -> tuple[_OptionCandidate, ...]:
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


def _option_matches(
    line: EstimateLine,
    candidate: _OptionCandidate,
    kind: str,
    requirements: frozenset[str],
) -> bool:
    if kind == "cable":
        return candidate.view.product_id == line.product_id
    candidate_requirements = _option_requirements(kind, candidate.match_text)
    return not requirements or requirements <= candidate_requirements


def _option_requirements(
    kind: str,
    text: str,
) -> frozenset[str]:
    normalized = _normalize(text)
    result: set[str] = set()
    if kind == "camera":
        result.update(_sensor_features(normalized))
        result.update(_resolution_features(normalized))
        result.update(_zoom_features(normalized))
    elif kind == "dvr":
        match = re.search(r"(?:nvr|em)\s*-?\s*[^0-9]{0,3}(\d+)", normalized)
        if match is not None:
            result.add(f"channel:{int(match.group(1))}")
        match = re.search(r"(\d+)\s*(?:ch|\ucc44\ub110)", normalized)
        if match is not None:
            result.add(f"channel:{int(match.group(1))}")
    elif kind == "switch":
        match = re.search(r"(\d+)\s*port", normalized)
        if match is not None:
            result.add(f"ports:{int(match.group(1))}")
        if "poe" in normalized:
            result.add("poe")
    elif kind == "hdd":
        match = re.search(r"(\d+(?:\.\d+)?)\s*tb", normalized)
        if match is not None:
            result.add(f"tb:{_number_key(match.group(1))}")
    else:
        result.update(
            f"number:{number}{unit}"
            for number, unit in re.findall(
                r"(\d+(?:\.\d+)?)\s*(port|tb|gb|ch|mm|m)", normalized
            )
        )
    return frozenset(result)


def _product_features(
    spec: str,
    raw_json: str,
) -> tuple[frozenset[str], frozenset[str]]:
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    synonym = str(payload.get("snymNm", ""))
    attributes = str(payload.get("pdctAtrbCdDtlNm", ""))
    normalized = _normalize(f"{synonym} {attributes}")
    core = {f"purpose:{_normalize(spec.rsplit(',', 1)[-1])}"}
    core.update(_resolution_features(normalized))
    core.update(_zoom_features(normalized))
    core.update(_sensor_features(normalized))
    for marker in (
        "\ubd88\uaf43",
        "\ud654\uc7ac",
        "\ucc28\ub7c9\ubc88\ud638",
        "\uc5f4\ud654\uc0c1",
        "\uc0b0\ubd88",
    ):
        if marker in normalized:
            core.add(f"special:{marker}")
    components: set[str] = set()
    for group in html.unescape(attributes).split("$")[1:]:
        for raw_component in group.split(","):
            component = _canonical_component(raw_component.split(":", 1)[0])
            if component is not None:
                components.add(component)
    return frozenset(core), frozenset(components)


def _resolution_features(text: str) -> set[str]:
    result = {
        f"resolution:{_number_key(value)}"
        for value in re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:mp|\uba54\uac00\ud53d\uc140)", text
        )
    }
    for value in re.findall(r"(\d+(?:\.\d+)?)\s*\ub9cc\ud654\uc18c", text):
        numeric = float(value) / 100
        result.add(f"resolution:{_number_key(str(numeric))}")
    return result


def _zoom_features(text: str) -> set[str]:
    result = {
        f"zoom:{_number_key(value)}"
        for value in re.findall(
            r"(?:\uad11\ud559|optical)\s*x?\s*(\d+(?:\.\d+)?)\s*(?:\ubc30)?\uc90c?",
            text,
        )
    }
    result.update(
        f"zoom:{_number_key(value)}"
        for value in re.findall(r"(\d+(?:\.\d+)?)\s*\ubc30\uc90c", text)
    )
    return result


def _sensor_features(text: str) -> set[str]:
    return {
        f"sensor:{_number_key(value)}"
        for value in re.findall(r"(\d+(?:\.\d+)?)\s*mm\s*cmos", text)
    }


def _line_component(line: EstimateLine) -> str | None:
    component = _canonical_component(line.item_name_snapshot)
    if component not in (None, "option"):
        return component
    item_name, _spec = _parse_option_label(line.spec_snapshot)
    return _canonical_component(item_name)


def _canonical_component(value: str) -> str | None:  # noqa: PLR0911
    normalized = _normalize(value).replace(" ", "")
    if not normalized:
        return None
    if "\uce74\uba54\ub77c" in normalized or "camera" in normalized:
        return "camera"
    if "\ub124\ud2b8\uc6cc\ud06c\uc2a4\uc704\uce58" in normalized:
        return "switch"
    if "\ub514\uc9c0\ud138\ube44\ub514\uc624\ub808\ucf54\ub354" in normalized:
        return "dvr"
    if "\ud558\ub4dc\ub514\uc2a4\ud06c\ub4dc\ub77c\uc774\ube0c" in normalized:
        return "hdd"
    if "\ucf00\uc774\ube14" in normalized:
        return "cable"
    if "\uc635\uc158" in normalized:
        return "option"
    return normalized


def _stored_parent_alternatives(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> tuple[_MainCandidate, ...]:
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


def _insert_comparisons(  # noqa: C901
    connection: sqlite3.Connection,
    line: EstimateLine,
    alternatives: tuple[ComparisonView, ...],
) -> None:
    selected = ComparisonView(
        "",
        line.product_id,
        line.relation_id,
        line.company_snapshot,
        line.spec_snapshot,
        line.unit_price_won_snapshot,
    )
    pool = (selected, *alternatives)
    baseline = next(
        (item for item in pool if item.company == KOREANET_COMPANY),
        None,
    )
    if baseline is None:
        return
    comparisons: list[ComparisonView] = [baseline]
    companies = {baseline.company}
    requires_distinct_ids = _requires_distinct_product_ids(connection, line)
    product_ids = {baseline.product_id}

    def append(item: ComparisonView, percentage: int | None) -> None:
        if item.company in companies or item.price_won < baseline.price_won:
            return
        if percentage is not None and not _within_price_limit(
            baseline.price_won, item.price_won, percentage
        ):
            return
        if requires_distinct_ids and item.product_id in product_ids:
            return
        comparisons.append(item)
        companies.add(item.company)
        product_ids.add(item.product_id)

    for percentage in PRICE_LADDER_PERCENTAGES:
        for item in pool:
            append(item, percentage)
            if len(comparisons) == COMPARISON_SLOT_COUNT:
                break
        if len(comparisons) == COMPARISON_SLOT_COUNT:
            break
    if len(comparisons) < COMPARISON_SLOT_COUNT:
        for item in pool:
            append(item, None)
            if len(comparisons) == COMPARISON_SLOT_COUNT:
                break
    _ = connection.executemany(
        "INSERT INTO estimate_comparisons VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (
                line.id,
                slot,
                item.product_id,
                item.relation_id,
                item.company,
                item.spec,
                item.price_won,
            )
            for slot, item in zip(("A", "B", "C"), comparisons, strict=False)
        ),
    )


def _has_comparisons(connection: sqlite3.Connection, line: EstimateLine) -> bool:
    rows = query(
        connection,
        """
        SELECT slot, product_id, company_snapshot, price_won_snapshot
        FROM estimate_comparisons WHERE estimate_line_id = ? ORDER BY slot
        """,
        (line.id,),
    ).fetchall()
    if len(rows) != COMPARISON_SLOT_COUNT or as_text(rows[0][0]) != "A":
        return False
    product_ids = [as_text(row[1]) for row in rows]
    companies = [as_text(row[2]) for row in rows]
    baseline_price = as_int(rows[0][3])
    return (
        companies[0] == KOREANET_COMPANY
        and len(companies) == len(set(companies))
        and (
            not _requires_distinct_product_ids(connection, line)
            or len(product_ids) == len(set(product_ids))
        )
        and all(baseline_price <= as_int(row[3]) for row in rows[1:])
    )


def _requires_distinct_product_ids(
    connection: sqlite3.Connection,
    line: EstimateLine,
) -> bool:
    if _line_component(line) != "switch" or "ports:8" not in _option_requirements(
        "switch", line.spec_snapshot
    ):
        return False
    if line.line_kind == "main":
        return True
    row = query(
        connection,
        "SELECT contract_method FROM priority_products WHERE product_id = ?",
        (line.parent_product_id,),
    ).fetchone()
    return row is None or as_text(row[0]) != "다수공급자계약"


def _within_price_limit(baseline: int, candidate: int, percentage: int) -> bool:
    return candidate * 100 <= baseline * (100 + percentage)


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
        parsed_item or _text_or(row[6], "\uc635\uc158"),
        parsed_spec or _text_or(row[7], as_text(row[4])),
        as_text(row[3]),
        _text_or(row[8], "\uac1c"),
        as_int(row[5]),
        quantity,
    )


def _parse_option_label(raw_label: str) -> tuple[str, str]:
    text = re.sub(r"^\[[^]]+\]\s*\[\d{8}\]\s*", "", raw_label).strip()
    text = re.sub(r"\s*:\s*[\d,]+\s*$", "", text)
    item_name, separator, spec = text.partition(",")
    if not separator:
        return text, text
    return item_name.strip(), spec.strip()


def _text_or(value: SqlValue, fallback: str) -> str:
    return fallback if value is None or value == "" else as_text(value)


def _normalize(value: str) -> str:
    decoded = html.unescape(value).casefold().replace("\u00d7", "x")
    return " ".join(re.sub(r"[^0-9a-z\uac00-\ud7a3.]+", " ", decoded).split())


def _number_key(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _cable_signature(item_name: str, spec: str) -> tuple[str, str] | None:
    if "\ucf00\uc774\ube14" not in item_name:
        return None
    parts = tuple(re.sub(r"\s+", "", part).casefold() for part in spec.split(","))
    if len(parts) >= ALTERNATIVE_COUNT:
        return (parts[-2], parts[-1])
    return (parts[0] if parts else "", "")
