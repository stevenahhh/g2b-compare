"""Canonical persisted comparator-cache payloads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Final, assert_never, final, override

from pydantic import ConfigDict, RootModel, TypeAdapter, ValidationError

type CacheJsonValue = (
    str | int | Decimal | bool | None | list[CacheJsonValue] | dict[str, CacheJsonValue]
)

CACHE_ROW_IDENTITY: Final = "cache-row-identity"
CACHE_ROW_DUPLICATE: Final = "cache-row-duplicate"
CACHE_DECIMAL_NONFINITE: Final = "cache-decimal-nonfinite"
CACHE_PAYLOAD_SCHEMA: Final = "cache-payload-schema"
CACHE_PAYLOAD_SCHEMA_VERSION: Final = "1"
CACHE_DOCUMENT_ADAPTER: Final = TypeAdapter(
    dict[str, CacheJsonValue],
    config=ConfigDict(strict=True),
)


class CachePayload(RootModel[CacheJsonValue]):
    """One frozen typed JSON cache document."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class CacheRow:
    """One anchor and slot payload before persistence."""

    anchor_id: str
    slot: int
    payload: CachePayload


@dataclass(frozen=True, slots=True)
class CachedSlot:
    """One verified canonical payload read from the active attempt."""

    slot: int
    payload: CachePayload
    payload_json: str
    payload_sha: str


@final
class CacheContractError(Exception):
    """A cache payload violates canonical content requirements."""

    code: str

    def __init__(self, code: str) -> None:
        """Initialize one stable machine-readable cache error."""
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code


def canonical_payload(payload: CachePayload) -> tuple[str, str]:
    """Return canonical JSON and its SHA-256."""
    document = _encode(payload.root)
    return document, hashlib.sha256(document.encode()).hexdigest()


def cache_content_sha(rows: tuple[CacheRow, ...]) -> str:
    """Hash exact ordered anchor-slot canonical payload content."""
    ordered = sorted(rows, key=lambda row: (row.anchor_id.encode(), row.slot))
    identities = tuple((row.anchor_id, row.slot) for row in ordered)
    if any(not anchor_id or slot not in range(1, 4) for anchor_id, slot in identities):
        raise CacheContractError(CACHE_ROW_IDENTITY)
    if len(frozenset(identities)) != len(identities):
        raise CacheContractError(CACHE_ROW_DUPLICATE)
    members: list[CacheJsonValue] = [
        {
            "anchor_id": row.anchor_id,
            "payload_sha": canonical_payload(row.payload)[1],
            "slot": row.slot,
        }
        for row in ordered
    ]
    document = _encode(members)
    return hashlib.sha256(document.encode()).hexdigest()


def require_payload_schema(payload: CachePayload) -> None:
    """Require the exact persisted cache payload schema version."""
    try:
        document = CACHE_DOCUMENT_ADAPTER.validate_python(payload.root)
    except ValidationError as error:
        raise CacheContractError(CACHE_PAYLOAD_SCHEMA) from error
    if document.get("schema_version") != CACHE_PAYLOAD_SCHEMA_VERSION:
        raise CacheContractError(CACHE_PAYLOAD_SCHEMA)


def _encode(value: CacheJsonValue) -> str:
    match value:
        case None:
            encoded = "null"
        case bool() as boolean:
            encoded = "true" if boolean else "false"
        case int() as integer:
            encoded = str(integer)
        case Decimal() as decimal:
            encoded = _decimal(decimal)
        case str() as text:
            encoded = json.dumps(text, ensure_ascii=False, separators=(",", ":"))
        case list() as values:
            encoded = "[" + ",".join(_encode(item) for item in values) + "]"
        case dict() as mapping:
            members = (
                _encode(key) + ":" + _encode(mapping[key])
                for key in sorted(mapping, key=lambda item: item.encode())
            )
            encoded = "{" + ",".join(members) + "}"
        case _:
            assert_never(value)
    return encoded


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CacheContractError(CACHE_DECIMAL_NONFINITE)
    if value.is_zero():
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")
