"""Typed JSON and XML provider-envelope parsing."""

from __future__ import annotations

from dataclasses import dataclass
from functools import singledispatch
from typing import ClassVar, Final, override
from xml.parsers import expat

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from g2b_compare.contracts.redact import JsonValue
from g2b_compare.db.hashes import sha256_text
from g2b_compare.sources.transport import MediaType

SUCCESS_CODE: Final = "00"
NO_DATA_CODES: Final = frozenset({"03", "NODATA_ERROR"})
type RawFields = dict[str, JsonValue]
ITEMS_REASON: Final = "provider items are not records"
ITEM_REASON: Final = "provider item is not a record"
DOCTYPE_REASON: Final = "XML document type is forbidden"
IS_FINAL: Final = True


@dataclass(frozen=True, slots=True)
class MalformedEnvelopeError(Exception):
    """A provider body does not match the typed JSON/XML envelope."""

    reason: str = "malformed provider envelope"

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class ProviderStatusError(Exception):
    """A decoded provider envelope reported a non-success result."""

    result_code: str
    result_message_sha256: str

    @override
    def __str__(self) -> str:
        return (
            f"provider result {self.result_code}; "
            f"message-sha256={self.result_message_sha256}"
        )


class _Header(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)
    result_code: str = Field(alias="resultCode")
    result_message: str = Field(alias="resultMsg")


class _Body(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)
    items: JsonValue = ""
    num_rows: int = Field(default=0, alias="numOfRows")
    page_no: int = Field(default=1, alias="pageNo")
    total_count: int = Field(default=0, alias="totalCount")


class _Response(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)
    header: _Header
    body: _Body


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", frozen=True)
    response: _Response


@dataclass(frozen=True, slots=True)
class ProviderPage:
    """One typed provider page with raw row fields preserved."""

    rows: tuple[RawFields, ...]
    page_number: int
    page_size: int
    total_count: int
    result_code: str
    result_message_sha256: str


def parse_envelope(content: bytes, media_type: MediaType) -> ProviderPage:
    """Parse an already status/content-type checked provider response."""
    parser = {
        MediaType.JSON: _parse_json,
        MediaType.XML: _parse_xml,
    }[media_type]
    try:
        envelope = parser(content)
    except (ValidationError, expat.ExpatError, UnicodeDecodeError):
        envelope = None
    if envelope is None:
        raise MalformedEnvelopeError
    response = envelope.response
    code = response.header.result_code
    message_sha256 = sha256_text(response.header.result_message)
    if code in NO_DATA_CODES:
        return ProviderPage(
            rows=(),
            page_number=response.body.page_no,
            page_size=response.body.num_rows,
            total_count=0,
            result_code=code,
            result_message_sha256=message_sha256,
        )
    if code != SUCCESS_CODE:
        raise ProviderStatusError(code, message_sha256)
    return ProviderPage(
        rows=_rows(response.body.items),
        page_number=response.body.page_no,
        page_size=response.body.num_rows,
        total_count=response.body.total_count,
        result_code=code,
        result_message_sha256=message_sha256,
    )


def _parse_json(content: bytes) -> _Envelope:
    return _Envelope.model_validate_json(content)


@singledispatch
def _rows(items: JsonValue) -> tuple[RawFields, ...]:
    _ = items
    raise MalformedEnvelopeError(ITEMS_REASON)


@_rows.register(type(None))
def rows_from_none(items: None) -> tuple[RawFields, ...]:
    """Map an absent provider items value to an empty page."""
    _ = items
    return ()


@_rows.register(str)
def rows_from_string(items: str) -> tuple[RawFields, ...]:
    """Accept only the provider's empty-string no-items representation."""
    if not items:
        return ()
    raise MalformedEnvelopeError(ITEMS_REASON)


@_rows.register(list)
def rows_from_list(items: list[JsonValue]) -> tuple[RawFields, ...]:
    """Parse a direct provider item list."""
    return tuple(_row(item) for item in items)


@_rows.register(dict)
def rows_from_mapping(items: RawFields) -> tuple[RawFields, ...]:
    """Parse wrapped or single-record provider items."""
    if "item" in items:
        return _rows(items["item"])
    return (items,)


@_rows.register(bool)
@_rows.register(int)
@_rows.register(float)
def rows_from_scalar(items: float) -> tuple[RawFields, ...]:
    """Reject scalar provider items values."""
    _ = items
    raise MalformedEnvelopeError(ITEMS_REASON)


@singledispatch
def _row(value: JsonValue) -> RawFields:
    _ = value
    raise MalformedEnvelopeError(ITEM_REASON)


@_row.register(dict)
def row_from_mapping(value: RawFields) -> RawFields:
    """Preserve every unknown field in a provider item record."""
    return value


def _parse_xml(content: bytes) -> _Envelope:
    collector = _XmlCollector()
    parser = expat.ParserCreate()
    parser.StartElementHandler = collector.start
    parser.EndElementHandler = collector.end
    parser.CharacterDataHandler = collector.text
    parser.StartDoctypeDeclHandler = collector.reject_doctype
    _ = parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    _ = parser.Parse(content, IS_FINAL)
    return collector.envelope()


class _XmlCollector:
    """Mutable Expat target used only while parsing one bounded response."""

    def __init__(self) -> None:
        self._stack: list[str] = []
        self._text: list[list[str]] = []
        self._header: RawFields = {}
        self._body: RawFields = {}
        self._rows: list[JsonValue] = []
        self._row: RawFields | None = None

    def start(self, name: str, _attributes: dict[str, str]) -> None:
        self._stack.append(name)
        self._text.append([])
        if name == "item":
            self._row = {}

    def text(self, value: str) -> None:
        if self._text:
            self._text[-1].append(value)

    def end(self, name: str) -> None:
        value = "".join(self._text.pop()).strip()
        parent = self._stack[-2] if len(self._stack) > 1 else ""
        if self._row is not None and parent == "item":
            self._row[name] = value
        if name == "item" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        if parent == "header":
            self._header[name] = value
        if parent == "body" and name != "items":
            self._body[name] = value
        _ = self._stack.pop()

    def reject_doctype(
        self,
        _name: str,
        _system_id: str | None,
        _public_id: str | None,
        _has_internal_subset: int,
    ) -> None:
        raise MalformedEnvelopeError(DOCTYPE_REASON)

    def envelope(self) -> _Envelope:
        self._body["items"] = {"item": self._rows}
        return _Envelope.model_validate(
            {"response": {"header": self._header, "body": self._body}}
        )
