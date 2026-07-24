"""Project parsed product specifications into deterministic index rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from g2b_compare.normalize.numbers import (
    InvalidQuantityError,
    UnsupportedNumberError,
)
from g2b_compare.normalize.spec_types import (
    RangeParseError,
    Relation,
    RelationParseError,
    SpecSemantic,
    UnitDimensionError,
)
from g2b_compare.normalize.specs import parse_specs
from g2b_compare.normalize.units import UnitAliasError

if TYPE_CHECKING:
    from decimal import Decimal

    from .attributes import ProductAttribute
    from .products import CanonicalProduct

type SourceKind = Literal["attr", "spec", "option"]
type IndexedRelation = Literal["eq", "le", "ge", "range"]

_NUMERIC_SPAN: Final = re.compile(r"\d+(?:[.,]\d+)?")
_PARSE_ERRORS: Final = (
    InvalidQuantityError,
    UnsupportedNumberError,
    RangeParseError,
    RelationParseError,
    UnitDimensionError,
    UnitAliasError,
)


class AttributeProjection(Protocol):
    """Attribute fields consumed by the spec projection."""

    @property
    def product_id(self) -> str:
        """Return the owning product identifier."""
        ...

    @property
    def attribute(self) -> ProductAttribute:
        """Return the normalized attribute."""
        ...


@dataclass(frozen=True, slots=True)
class ProductSpecRow:
    """One searchable normalized product specification."""

    product_id: str
    source_kind: SourceKind
    attribute_key: str
    dimension: str
    relation: IndexedRelation
    value_low: str | None
    value_high: str | None
    canonical_unit: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class CategoryParseStat:
    """One deterministic category parsing coverage row."""

    category_no: str
    detail_category_no: str
    product_count: int
    numeric_span_count: int
    parsed_semantic_count: int
    attribute_covered_count: int


def build_spec_projection(
    products: tuple[CanonicalProduct, ...],
    attributes: tuple[AttributeProjection, ...],
    covered_product_ids: tuple[str, ...],
    option_texts: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[ProductSpecRow, ...], tuple[CategoryParseStat, ...]]:
    """Parse authoritative attribute and specification text."""
    by_product: dict[str, list[AttributeProjection]] = {}
    for item in attributes:
        by_product.setdefault(item.product_id, []).append(item)
    options_by_product: dict[str, list[str]] = {}
    for product_id, text in option_texts:
        options_by_product.setdefault(product_id, []).append(text)
    rows: list[ProductSpecRow] = []
    numeric_counts: dict[tuple[str, str], int] = {}
    parsed_counts: dict[tuple[str, str], int] = {}
    product_counts: dict[tuple[str, str], int] = {}
    product_categories = {item.product_id: item.category_key for item in products}
    for product in products:
        row_start = len(rows)
        category = product.category_key
        product_counts[category] = product_counts.get(category, 0) + 1
        texts = (product.spec_name, product.detail, product.characteristic)
        numeric_counts[category] = numeric_counts.get(category, 0) + sum(
            len(_NUMERIC_SPAN.findall(text)) for text in texts
        )
        for text in texts:
            rows.extend(_rows(product.product_id, "spec", text, len(rows)))
        for item in by_product.get(product.product_id, []):
            value = item.attribute.raw_value
            numeric_counts[category] += len(_NUMERIC_SPAN.findall(value))
            rows.extend(_rows(product.product_id, "attr", value, len(rows)))
        for text in options_by_product.get(product.product_id, []):
            numeric_counts[category] += len(_NUMERIC_SPAN.findall(text))
            rows.extend(_rows(product.product_id, "option", text, len(rows)))
        parsed_counts[category] = parsed_counts.get(category, 0) + len(rows) - row_start
    covered = frozenset(covered_product_ids)
    stats = tuple(
        CategoryParseStat(
            category[0],
            category[1],
            product_counts[category],
            numeric_counts.get(category, 0),
            parsed_counts.get(category, 0),
            sum(
                product_id in covered
                for product_id, owned in product_categories.items()
                if owned == category
            ),
        )
        for category in sorted(product_counts)
    )
    return tuple(rows), stats


def _rows(
    product_id: str,
    source_kind: SourceKind,
    text: str,
    start: int,
) -> tuple[ProductSpecRow, ...]:
    if not text:
        return ()
    try:
        semantics = parse_specs(text).semantics
    except _PARSE_ERRORS:
        return ()
    return tuple(
        _row(product_id, source_kind, semantic, start + ordinal)
        for ordinal, semantic in enumerate(semantics)
    )


def _row(
    product_id: str,
    source_kind: SourceKind,
    semantic: SpecSemantic,
    ordinal: int,
) -> ProductSpecRow:
    relation, low, high = _interval(semantic)
    return ProductSpecRow(
        product_id,
        source_kind,
        semantic.attribute_key or "unknown",
        semantic.dimension,
        relation,
        _decimal(low),
        _decimal(high),
        semantic.canonical_unit,
        ordinal,
    )


def _interval(
    semantic: SpecSemantic,
) -> tuple[IndexedRelation, Decimal | None, Decimal | None]:
    match semantic.relation:
        case Relation.EQ:
            return "eq", semantic.value, semantic.value
        case Relation.GTE | Relation.GT:
            return "ge", semantic.value, None
        case Relation.LTE | Relation.LT:
            return "le", None, semantic.value
        case Relation.RANGE:
            return "range", semantic.lower, semantic.upper


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
