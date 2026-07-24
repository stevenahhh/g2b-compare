"""Parse displayable product attributes from collected catalog payloads."""

from __future__ import annotations

import html
import re
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from g2b_compare.priority_models import ProductAttribute

NAME_FIELD_COUNT: Final = 2


class _RawProductAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    names: str = Field(default="", alias="pdctAtrbNm")
    values: str = Field(default="", alias="pdctAtrbCdDtlNm")
    synonyms: str = Field(default="", alias="snymNm")


def parse_product_attributes(raw_json: str) -> tuple[ProductAttribute, ...]:
    """Return catalog attributes in the order used by the product UI."""
    try:
        raw = _RawProductAttributes.model_validate_json(raw_json)
    except ValidationError:
        return ()
    names = tuple(
        fields[-2]
        for entry in raw.names.split("|")
        if len(fields := entry.split("$")) >= NAME_FIELD_COUNT
    )
    values = tuple(_clean(value) for value in raw.values.split("$"))
    pairs = tuple(
        ProductAttribute(name=_clean(name), value=value)
        for name, value in zip(names, values, strict=False)
        if name and value
    )
    composition = next((item for item in pairs if item.name == "구성"), None)
    options = _component_options(composition, raw.synonyms)
    ordered = tuple(item for item in pairs if item.name == "구성")
    if options:
        ordered += (ProductAttribute(name="옵션/기타", value=options),)
    return ordered + tuple(item for item in pairs if item.name != "구성")


def _component_options(
    composition: ProductAttribute | None,
    synonyms: str,
) -> str:
    if composition is None:
        return ""
    components = tuple(
        _key(part.split(":", 1)[0]) for part in composition.value.split(",")
    )
    segments = tuple(_clean(part) for part in synonyms.split("||"))
    matches: list[str] = []
    for component in components:
        match = next(
            (
                segment
                for segment in segments
                if ":" in segment and _key(segment.split(":", 1)[0]) == component
            ),
            "",
        )
        if match:
            matches.append(match)
    return ", ".join(matches)


def _clean(value: str) -> str:
    return html.unescape(value).strip()


def _key(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
