"""Preserve delivery option roles as event-level observations."""

from dataclasses import dataclass
from typing import Final

DELIVERY_OPERATION: Final = "getDlvrReqDtlInfoList"


@dataclass(frozen=True, slots=True)
class DeliveryCandidate:
    """Typed fields selected from one provider delivery row."""

    source_ordinal: int
    delivery_request_key: str | None
    item_sequence: str | None
    change_sequence: str | None
    product_id: str | None
    option_role: str


@dataclass(frozen=True, slots=True)
class DeliveryIdentity:
    """Manifest-proven stable identity for one delivery row."""

    delivery_request_key: str
    item_sequence: str
    change_sequence: str


@dataclass(frozen=True, slots=True)
class DeliveryRoleEvent:
    """One contextual option role with source provenance."""

    identity: DeliveryIdentity
    product_id: str
    role_raw: str
    source_operation: str
    source_ordinal: int
    observed_at: str


@dataclass(frozen=True, slots=True)
class QuarantinedDeliveryCandidate:
    """A row excluded because its stable identity is incomplete."""

    source_ordinal: int
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeliveryParseResult:
    """Partition delivery rows into role events and quarantined rows."""

    events: tuple[DeliveryRoleEvent, ...]
    quarantined: tuple[QuarantinedDeliveryCandidate, ...]
    relations: tuple[()] = ()


def parse_delivery_candidates(
    candidates: tuple[DeliveryCandidate, ...],
    observed_at: str,
) -> DeliveryParseResult:
    """Parse typed provider candidates without inferring relationships."""
    events: list[DeliveryRoleEvent] = []
    quarantined: list[QuarantinedDeliveryCandidate] = []
    for candidate in candidates:
        request_key = candidate.delivery_request_key
        item_sequence = candidate.item_sequence
        change_sequence = candidate.change_sequence
        product_id = candidate.product_id
        identity_values = (request_key, item_sequence, change_sequence, product_id)
        if (
            request_key is None
            or item_sequence is None
            or change_sequence is None
            or product_id is None
        ):
            missing_fields = tuple(
                field
                for field, value in zip(
                    ("dlvrReqNo", "prdctSno", "dlvrReqChgOrd", "prdctIdntNo"),
                    identity_values,
                    strict=True,
                )
                if value is None
            )
            quarantined.append(
                QuarantinedDeliveryCandidate(candidate.source_ordinal, missing_fields)
            )
            continue
        blank_fields = tuple(
            field
            for field, value in (
                ("dlvrReqNo", request_key),
                ("prdctSno", item_sequence),
                ("prdctIdntNo", product_id),
            )
            if not value
        )
        if blank_fields:
            quarantined.append(
                QuarantinedDeliveryCandidate(candidate.source_ordinal, blank_fields)
            )
            continue
        events.append(
            DeliveryRoleEvent(
                identity=DeliveryIdentity(request_key, item_sequence, change_sequence),
                product_id=product_id,
                role_raw=candidate.option_role,
                source_operation=DELIVERY_OPERATION,
                source_ordinal=candidate.source_ordinal,
                observed_at=observed_at,
            )
        )
    return DeliveryParseResult(tuple(events), tuple(quarantined))
