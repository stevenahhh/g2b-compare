"""Extract comparable product and option features."""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from .estimate_text import (
    normalize as _normalize,
)
from .estimate_text import (
    number_key as _number_key,
)
from .estimate_text import (
    parse_option_label as _parse_option_label,
)

if TYPE_CHECKING:
    from g2b_compare.services import EstimateLine

PRODUCT_PAYLOAD_ADAPTER: Final = TypeAdapter(dict[str, object])


def option_requirements(kind: str, text: str) -> frozenset[str]:
    """Extract normalized compatibility requirements for one option kind."""
    normalized = _normalize(text)
    if kind == "camera":
        return frozenset(
            _sensor_features(normalized)
            | _resolution_features(normalized)
            | _zoom_features(normalized)
        )
    if kind == "dvr":
        return _dvr_requirements(normalized)
    if kind == "switch":
        return _switch_requirements(normalized)
    if kind == "hdd":
        match = re.search(r"(\d+(?:\.\d+)?)\s*tb", normalized)
        return (
            frozenset({f"tb:{_number_key(match.group(1))}"})
            if match is not None
            else frozenset()
        )
    return frozenset(
        f"number:{match.group(1)}{match.group(2)}"
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(port|tb|gb|ch|mm|m)",
            normalized,
        )
    )


def product_features(
    spec: str,
    raw_json: str,
) -> tuple[frozenset[str], frozenset[str]]:
    """Extract main-product purpose and component features."""
    try:
        payload = PRODUCT_PAYLOAD_ADAPTER.validate_json(raw_json)
    except ValidationError:
        payload = {}
    synonym = str(payload.get("snymNm", ""))
    attributes = str(payload.get("pdctAtrbCdDtlNm", ""))
    normalized = _normalize(f"{synonym} {attributes}")
    core = {f"purpose:{_normalize(spec.rsplit(',', 1)[-1])}"}
    core.update(_resolution_features(normalized))
    core.update(_zoom_features(normalized))
    core.update(_sensor_features(normalized))
    for marker in ("불꽃", "화재", "차량번호", "열화상", "산불"):
        if marker in normalized:
            core.add(f"special:{marker}")
    components: set[str] = set()
    for group in html.unescape(attributes).split("$")[1:]:
        for raw_component in group.split(","):
            component = canonical_component(raw_component.split(":", 1)[0])
            if component is not None:
                components.add(component)
    return frozenset(core), frozenset(components)


def _resolution_features(text: str) -> set[str]:
    result = {
        f"resolution:{_number_key(match.group(1))}"
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:mp|메가픽셀)", text)
    }
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*만화소", text):
        numeric = float(match.group(1)) / 100
        result.add(f"resolution:{_number_key(str(numeric))}")
    return result


def _zoom_features(text: str) -> set[str]:
    result = {
        f"zoom:{_number_key(match.group(1))}"
        for match in re.finditer(
            r"(?:광학|optical)\s*x?\s*(\d+(?:\.\d+)?)\s*(?:배)?줌?", text
        )
    }
    result.update(
        f"zoom:{_number_key(match.group(1))}"
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*배줌", text)
    )
    return result


def _sensor_features(text: str) -> set[str]:
    return {
        f"sensor:{_number_key(match.group(1))}"
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*mm\s*cmos", text)
    }


def line_component(line: EstimateLine) -> str | None:
    """Return the canonical component represented by one estimate line."""
    component = canonical_component(line.item_name_snapshot)
    if component not in (None, "option"):
        return component
    item_name, _spec = _parse_option_label(line.spec_snapshot)
    return canonical_component(item_name)


def canonical_component(value: str) -> str | None:  # noqa: PLR0911
    """Normalize a product or option label to its component family."""
    normalized = _normalize(value).replace(" ", "")
    if not normalized:
        return None
    if "카메라" in normalized or "camera" in normalized:
        return "camera"
    if "네트워크스위치" in normalized:
        return "switch"
    if "디지털비디오레코더" in normalized:
        return "dvr"
    if "하드디스크드라이브" in normalized:
        return "hdd"
    if "케이블" in normalized:
        return "cable"
    if "옵션" in normalized:
        return "option"
    return normalized


def _dvr_requirements(normalized: str) -> frozenset[str]:
    channels: set[str] = set()
    for pattern in (
        r"(?:nvr|em)\s*-?\s*[^0-9]{0,3}(\d+)",
        r"(\d+)\s*(?:ch|채널)",
    ):
        match = re.search(pattern, normalized)
        if match is not None:
            channels.add(f"channel:{int(match.group(1))}")
    return frozenset(channels)


def _switch_requirements(normalized: str) -> frozenset[str]:
    result: set[str] = set()
    match = re.search(r"(\d+)\s*port", normalized)
    if match is not None:
        result.add(f"ports:{int(match.group(1))}")
    if "poe" in normalized:
        result.add("poe")
    return frozenset(result)
