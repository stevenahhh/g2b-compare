"""Strict response pagination metadata for attribute pages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


@final
class AttributePageMetadataError(Exception):
    """Reject missing or invalid provider pagination metadata."""

    @override
    def __str__(self) -> str:
        return "page-metadata-invalid"


@dataclass(frozen=True, slots=True)
class AttributePageMetadata:
    """Provider-reported pagination values used instead of request values."""

    page_no: int
    page_size: int
    total_count: int


class _BodyMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    page_no: int = Field(alias="pageNo", gt=0)
    page_size: int = Field(alias="numOfRows", gt=0)
    total_count: int = Field(alias="totalCount", ge=0)


class _ResponseMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    body: _BodyMetadata


class _EnvelopeMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    response: _ResponseMetadata


def _reject_duplicate_keys(
    pairs: list[tuple[str, JsonValue]],
) -> None:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise AttributePageMetadataError
        seen.add(key)


def parse_attribute_page_metadata(content: bytes) -> AttributePageMetadata:
    """Parse required pageNo, numOfRows, and totalCount fields."""
    try:
        json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys).decode(
            content.decode("utf-8")
        )
        body = _EnvelopeMetadata.model_validate_json(content).response.body
    except (
        AttributePageMetadataError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValidationError,
    ):
        raise AttributePageMetadataError from None
    return AttributePageMetadata(body.page_no, body.page_size, body.total_count)
