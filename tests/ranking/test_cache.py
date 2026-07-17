from __future__ import annotations

from decimal import Decimal

from g2b_compare.ranking.cache import (
    CachePayload,
    CacheRow,
    cache_content_sha,
    canonical_payload,
)


def test_canonical_payload_equates_key_order_and_decimal_spelling() -> None:
    # Given: semantically equal payloads with different key and Decimal spelling.
    first = CachePayload({"z": Decimal("1.00"), "a": [1, Decimal("0.5000")]})
    second = CachePayload({"a": [1, Decimal("0.5")], "z": Decimal("1.0")})

    # When: both documents cross the canonical cache boundary.
    first_document = canonical_payload(first)
    second_document = canonical_payload(second)

    # Then: JCS bytes and payload SHA are identical.
    assert first_document == second_document


def test_canonical_payload_preserves_array_order() -> None:
    # Given: the same values in two meaningfully different array orders.
    first = CachePayload({"matched_quantities": ["first", "second"]})
    second = CachePayload({"matched_quantities": ["second", "first"]})

    # When: canonical payload SHAs are calculated.
    first_sha = canonical_payload(first)[1]
    second_sha = canonical_payload(second)[1]

    # Then: array order remains content-significant.
    assert first_sha != second_sha


def test_cache_content_sha_is_row_order_independent_but_slot_sensitive() -> None:
    # Given: the same two exact cache rows in different arrival order.
    payload = CachePayload({"schema_version": "1"})
    rows = (CacheRow("B", 2, payload), CacheRow("A", 1, payload))

    # When: attempt content is framed canonically.
    forward = cache_content_sha(rows)
    reverse = cache_content_sha(tuple(reversed(rows)))
    changed_slot = cache_content_sha((CacheRow("B", 3, payload), rows[1]))

    # Then: arrival order is ignored while the semantic slot is not.
    assert forward == reverse
    assert forward != changed_slot


def test_cache_content_sha_matches_exact_payload_sha_jcs_golden() -> None:
    # Given: exact A/B anchor slots using the shipped schema-one payload fixture.
    rows = tuple(
        CacheRow(anchor, slot, _golden_payload(anchor, slot))
        for anchor in ("A", "B")
        for slot in range(1, 4)
    )

    # When: attempt content is hashed from canonical payload identities.
    digest = cache_content_sha(rows)

    # Then: bytes equal the independent JCS payload-SHA golden.
    assert digest == "d54508ae23788d71648cbec61333f3eace5b1d539352c16625525f3d29da9e6b"


def _golden_payload(anchor_id: str, slot: int) -> CachePayload:
    return CachePayload(
        {
            "anchor_id": anchor_id,
            "candidate_id": f"C-{slot}",
            "matched_quantities": [],
            "missing_reasons": [],
            "schema_version": "1",
            "scores": {"S": Decimal("0.500000")},
            "slot": slot,
        }
    )
