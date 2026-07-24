"""Delivery detail option-role adapter contracts."""

from g2b_compare.sources.delivery_detail import (
    DELIVERY_OPERATION,
    DeliveryCandidate,
    parse_delivery_candidates,
)


def test_preserves_event_level_roles_without_api_relations() -> None:
    # Given
    candidates = tuple(
        DeliveryCandidate(
            source_ordinal=ordinal,
            delivery_request_key="1224193016",
            item_sequence=str(ordinal),
            change_sequence="02",
            product_id=f"2468467{ordinal}",
            option_role=role,
        )
        for ordinal, role in enumerate(
            ("대표품목", "별도구매선택품목", "동시구매품목"),
            start=1,
        )
    )

    # When
    result = parse_delivery_candidates(candidates, observed_at="2026-07-16T00:00:00Z")

    # Then
    assert tuple(event.role_raw for event in result.events) == (
        "대표품목",
        "별도구매선택품목",
        "동시구매품목",
    )
    assert tuple(event.product_id for event in result.events) == (
        "24684671",
        "24684672",
        "24684673",
    )
    assert all(event.source_operation == DELIVERY_OPERATION for event in result.events)
    assert all(event.observed_at == "2026-07-16T00:00:00Z" for event in result.events)
    assert result.relations == ()
    assert result.quarantined == ()


def test_quarantines_missing_identity_and_accepts_empty_change_sequence() -> None:
    # Given
    candidates = (
        DeliveryCandidate(1, "1224193016", "1", "", "24684676", "대표품목"),
        DeliveryCandidate(2, None, "2", "01", "24684677", "별도구매선택품목"),
        DeliveryCandidate(3, "1224193016", None, "01", "24684678", "동시구매품목"),
        DeliveryCandidate(4, "1224193016", "4", None, "24684679", "대표품목"),
    )

    # When
    result = parse_delivery_candidates(candidates, observed_at="2026-07-16T00:00:00Z")

    # Then
    assert len(result.events) == 1
    assert result.events[0].identity.change_sequence == ""
    assert tuple(item.source_ordinal for item in result.quarantined) == (2, 3, 4)
    assert tuple(item.missing_fields for item in result.quarantined) == (
        ("dlvrReqNo",),
        ("prdctSno",),
        ("dlvrReqChgOrd",),
    )
    assert result.relations == ()
