from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.db.connection import connect
from g2b_compare.db.sql import query
from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.materialize.products import merge_products
from g2b_compare.materialize.spec_index import build_spec_projection
from g2b_compare.normalize import parse_specs
from g2b_compare.ranking.topk import RankableProduct, top_three
from g2b_compare.services.release import ReleaseCoordinator
from g2b_compare.services.search import execute_search
from g2b_compare.services.search_models import SearchRequest
from g2b_compare.services.sqlite_search import SqliteSearchReader
from g2b_compare.web.viewmodels import search_view
from tests.materialize.support import offer
from tests.services.release_support import MutableClock, PayloadBuilder
from tests.services.sqlite_search_support import search_database

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("raw", "value", "unit"),
    [
        ("1CH", Decimal(1), "channel"),
        ("500GB", Decimal(500_000_000_000), "byte"),
        ("4.5kg", Decimal("4.5"), "kg"),
        ("-20°C", Decimal(-20), "°C"),
    ],
)
def test_pv2_units(raw: str, value: Decimal, unit: str) -> None:
    semantic = parse_specs(raw).semantics[0]
    assert semantic.value == value
    assert semantic.canonical_unit == unit


def test_pv2_projection_preserves_real_source_kinds() -> None:
    product = merge_products(
        (offer(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "offer-1"),),
        (),
    )[0]

    rows, stats = build_spec_projection(
        (product,),
        (),
        (),
        (("P-1", "선택사양 500GB"),),
    )

    assert {row.source_kind for row in rows} == {"spec", "option"}
    assert stats[0].parsed_semantic_count == len(rows)
    assert stats[0].numeric_span_count == 3


def test_pv2_filter_facets_and_twelve_item_ui_cap(tmp_path: Path) -> None:
    fixture = search_database(tmp_path / "search.sqlite3")
    with connect(fixture.release.path) as connection:
        for ordinal, (product_id, value) in enumerate(
            (("A", "8000000"), ("B", "8000000"), ("C", "8000000"), ("D", "4000000"))
        ):
            _ = query(
                connection,
                """INSERT INTO product_spec_index VALUES(
                   10,?,'attr','resolution','resolution','eq',? ,?,'pixel',?)""",
                (product_id, value, value, ordinal),
            )
    result = ReleaseCoordinator(
        fixture.release.path,
        MutableClock(),
    ).coordinate(
        fixture.release.candidate,
        PayloadBuilder(fixture.release.path),
    )
    assert result.pin is not None
    reader = SqliteSearchReader(fixture.release.path)

    response = execute_search(
        SearchRequest(product_name="영상감시장치", spec_filter="800만화소"),
        reader,
    )

    assert {item.product.rankable.product_id for item in response.results} == {
        "A",
        "B",
        "C",
    }
    assert response.facets[0].display_value == "800만화소"
    assert response.facets[0].count == 3
    facets = tuple(response.facets[0] for _index in range(13))
    capped = response.__class__(
        response.status,
        response.release,
        response.selected_category,
        response.selected_price_unit,
        response.price_tolerance_pct,
        response.total_results,
        response.page,
        response.page_size,
        response.results,
        facets,
    )
    facet_view = search_view(capped, {})["facets"]
    assert isinstance(facet_view, list)
    assert len(facet_view) == 12


def test_pv2_comparator_slots_prefer_distinct_contractors() -> None:
    anchor = _rankable("A", "corp-a")
    candidates = (
        _rankable("B", "corp-a"),
        _rankable("C", "corp-b"),
        _rankable("D", "corp-c"),
        _rankable("E", "corp-a"),
    )

    slots = top_three(anchor, candidates)

    assert [slot.comparator.product_id for slot in slots if slot.comparator] == [
        "B",
        "C",
        "D",
    ]
    assert not any(slot.same_corp_as_higher_slot for slot in slots)


def _rankable(product_id: str, corporation: str) -> RankableProduct:
    return RankableProduct(
        product_id=product_id,
        category_key=("46", "4601"),
        product_name_key="영상감시장치",
        option_text="800만화소",
        active=True,
        price=ComparisonPrice(
            active=True,
            amount_won=1_000_000,
            unit_key="대",
            offer_key=("mas", product_id),
            reason=None,
        ),
        contract_corp_ids=(corporation,),
    )
