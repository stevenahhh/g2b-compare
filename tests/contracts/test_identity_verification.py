from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.verification import has_stable_keys, schema_failure
from g2b_compare.contracts.wire import ObservedPage, WireContractError, parse_page

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonScalar


def _page(*rows: dict[str, JsonScalar]) -> ObservedPage:
    return ObservedPage(
        rows=rows,
        fields=tuple(sorted(rows[0])),
        reported_page_size=len(rows),
        total_count=len(rows),
        payload_sha256="a" * 64,
    )


def _payload(rows: list[dict[str, str]]) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": rows,
                    "numOfRows": len(rows),
                    "pageNo": 1,
                    "totalCount": len(rows),
                },
            }
        },
        separators=(",", ":"),
    ).encode()


def test_schema_verification_accepts_reordered_identity_set() -> None:
    # Given: two pages with the same schema and identity set in different order.
    first = _page({"id": "A", "value": "1"}, {"id": "B", "value": "2"})
    current = _page({"id": "B", "value": "2"}, {"id": "A", "value": "1"})

    # When: schema verification compares the pages.
    failure = schema_failure(first, current, ("id",))

    # Then: provider ordering does not create identity drift.
    assert failure is None


def test_schema_verification_accepts_expansion_with_different_first_row() -> None:
    # Given: discovery has one row and verification expands with another row first.
    first = _page({"id": "A", "value": "1"})
    current = _page({"id": "B", "value": "2"}, {"id": "A", "value": "1"})

    # When: schema verification compares the pages.
    failure = schema_failure(first, current, ("id",))

    # Then: page-size expansion does not compare provider identity values.
    assert failure is None


def test_duplicate_composite_identity_is_rejected() -> None:
    # Given: one page repeats a complete composite identity.
    rows: tuple[dict[str, JsonScalar], ...] = (
        {"left": "A", "right": "1"},
        {"left": "A", "right": "1"},
    )

    # When: stable identities are verified.
    valid = has_stable_keys(rows, ("left", "right"))

    # Then: duplicate identities are rejected.
    assert valid is False


def test_non_first_heterogeneous_field_set_is_rejected() -> None:
    # Given: a later provider row has a different field set from the first.
    content = _payload([{"id": "A", "value": "1"}, {"id": "B", "extra": "2"}])

    # When/Then: the strict wire boundary rejects the page.
    with pytest.raises(WireContractError, match="malformed-envelope"):
        _ = parse_page(content, Operation.GET_MAS_CONTRACT_PRODUCT_INFO)


def test_attribute_source_ordinal_is_canonical_across_reordering() -> None:
    # Given: equal logical attribute rows arrive in opposite orders.
    rows = [
        {"prdctIdntNo": "P1", "attrNm": "resolution", "attrVal": "8MP"},
        {"prdctIdntNo": "P1", "attrNm": "resolution", "attrVal": "4K"},
    ]

    # When: both pages cross the operation-aware wire boundary.
    first = parse_page(_payload(rows), Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE)
    reordered = parse_page(
        _payload(list(reversed(rows))),
        Operation.GET_PRODUCT_INDIVIDUAL_ATTRIBUTE,
    )

    # Then: canonical content, not arrival order, determines source ordinal.
    assert first.rows == reordered.rows
    assert tuple(row["source_ordinal"] for row in first.rows) == (0, 1)
