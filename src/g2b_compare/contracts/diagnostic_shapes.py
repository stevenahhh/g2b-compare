"""Sanitized response shapes for provider-limit diagnostics."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from g2b_compare.contracts.redact import JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

_METADATA_FIELDS: Final = frozenset({"numOfRows", "pageNo", "totalCount"})


class ScalarType(StrEnum):
    """JSON scalar families retained without textual values."""

    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    NULL = "null"


class MetadataOccurrence(BaseModel):
    """Safe location and numeric fact for an exact pagination field."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    pointer: str
    scalar_type: ScalarType
    numeric_value: int | float | None


class ItemsShape(BaseModel):
    """Items container cardinality without item content."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    shape: Literal[
        "direct-list", "wrapped-list", "wrapped-single", "missing", "other"
    ]
    count: int


class LimitDiagnostic(BaseModel):
    """Allowlisted structural evidence from exactly one response."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    http_status: int
    content_type_family: Literal["json", "text", "xml", "binary", "missing", "other"]
    top_level_keys: tuple[str, ...]
    response_keys: tuple[str, ...]
    body_keys: tuple[str, ...]
    metadata: tuple[MetadataOccurrence, ...]
    items: ItemsShape
    request_fingerprint: str = ""


def inspect_limit_response(
    status: int,
    content_type: str,
    content: bytes,
    *,
    request_fingerprint: str = "",
    secret_values: tuple[str, ...] = (),
) -> LimitDiagnostic:
    """Reduce a response to allowlisted structural metadata."""
    try:
        root = RootModel[JsonValue].model_validate_json(content).root
    except ValidationError:
        root = None
    top = root if isinstance(root, dict) else {}
    response = top.get("response")
    response_map = response if isinstance(response, dict) else {}
    body = response_map.get("body")
    body_map = body if isinstance(body, dict) else {}
    metadata: list[MetadataOccurrence] = []
    _collect_metadata(root, "", metadata)
    return LimitDiagnostic(
        http_status=status,
        content_type_family=_content_type_family(content_type),
        top_level_keys=_safe_keys(top, secret_values),
        response_keys=_safe_keys(response_map, secret_values),
        body_keys=_safe_keys(body_map, secret_values),
        metadata=tuple(sorted(metadata, key=lambda item: item.pointer)),
        items=_items_shape(body_map),
        request_fingerprint=request_fingerprint,
    )


def _collect_metadata(
    value: JsonValue, pointer: str, output: list[MetadataOccurrence]
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}"
            if key in _METADATA_FIELDS and not isinstance(child, (dict, list)):
                scalar_type, numeric = _scalar(child)
                output.append(
                    MetadataOccurrence(
                        pointer=child_pointer,
                        scalar_type=scalar_type,
                        numeric_value=numeric,
                    )
                )
            _collect_metadata(child, child_pointer, output)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_metadata(child, f"{pointer}/{index}", output)


def _scalar(
    value: str | float | bool | None,
) -> tuple[ScalarType, int | float | None]:
    if value is None:
        return ScalarType.NULL, None
    if isinstance(value, bool):
        return ScalarType.BOOLEAN, None
    if isinstance(value, int):
        return ScalarType.INTEGER, value
    if isinstance(value, float):
        return ScalarType.NUMBER, value
    return ScalarType.STRING, None


def _items_shape(body: Mapping[str, JsonValue]) -> ItemsShape:
    items = body.get("items")
    if isinstance(items, list):
        return ItemsShape(shape="direct-list", count=len(items))
    if isinstance(items, dict):
        wrapped = items.get("item")
        if isinstance(wrapped, list):
            return ItemsShape(shape="wrapped-list", count=len(wrapped))
        if isinstance(wrapped, dict):
            return ItemsShape(shape="wrapped-single", count=1)
        return ItemsShape(shape="other", count=0)
    return ItemsShape(shape="missing" if items is None else "other", count=0)


def _safe_keys(
    value: Mapping[str, JsonValue], secrets: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(sorted(_redact_key(key, secrets) for key in value))


def _redact_key(key: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            key = key.replace(secret, "[REDACTED]")
    return key


def _content_type_family(
    value: str,
) -> Literal["json", "text", "xml", "binary", "missing", "other"]:
    media_type = value.partition(";")[0].strip().casefold()
    if not media_type:
        return "missing"
    if media_type == "application/json" or media_type.endswith("+json"):
        return "json"
    if media_type.endswith(("/xml", "+xml")):
        return "xml"
    if media_type.startswith("text/"):
        return "text"
    if media_type == "application/octet-stream":
        return "binary"
    return "other"
