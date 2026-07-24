"""Project persisted share-link evidence into safe URLs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, cast
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue, RootModel, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from .types import ViewValue

SHOP_HOME: Final = "https://shop.g2b.go.kr/"
HTTP_OK: Final = 200
_ITEM_KEY: Final = re.compile(r"^[0-9A-Za-z_-]{1,100}$")
_EVIDENCE_KEYS: Final = frozenset(
    {"share_link_preflight", "stable_contract_item_management_number"}
)
_PREFLIGHT_KEYS: Final = frozenset({"final_host", "no_redirect", "status"})


@dataclass(frozen=True, slots=True)
class ProductLink:
    """Represent a safe destination and optional identifier-copy fallback."""

    href: str
    copy_id: str | None


class _PersistedProductLinks(RootModel[dict[str, dict[str, JsonValue]]]):
    root: dict[str, dict[str, JsonValue]]


class _PersistedManifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    product_links: _PersistedProductLinks


def load_product_links(path: Path | None) -> Mapping[str, Mapping[str, ViewValue]]:
    """Read the persisted Todo 2 link manifest once without network access."""
    if path is None:
        return {}
    try:
        document = _PersistedManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return {}
    return document.product_links.root


def stable_product_link(manifest: Mapping[str, ViewValue]) -> str | None:
    """Create a deep link only when persisted preflight evidence is complete."""
    if frozenset(manifest) != _EVIDENCE_KEYS:
        return None
    value = manifest.get("stable_contract_item_management_number")
    preflight = manifest.get("share_link_preflight")
    if not isinstance(value, str) or _ITEM_KEY.fullmatch(value) is None:
        return None
    if not isinstance(preflight, Mapping):
        return None
    evidence = cast("Mapping[str, ViewValue]", preflight)
    if frozenset(evidence) != _PREFLIGHT_KEYS:
        return None
    if (
        evidence.get("no_redirect") is not True
        or evidence.get("final_host") != "shop.g2b.go.kr"
        or evidence.get("status") != HTTP_OK
    ):
        return None
    encoded = quote(value, safe="-._~")
    return f"https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo={encoded}"


def product_link(
    manifest: Mapping[str, ViewValue],
    product_id: str,
    *,
    contract_item_key: str = "",
) -> ProductLink:
    """Prefer a verified or live contract-item link, then preserve the product ID."""
    deep_link = stable_product_link(manifest)
    if deep_link is None and _ITEM_KEY.fullmatch(contract_item_key) is not None:
        encoded = quote(contract_item_key, safe="-._~")
        deep_link = f"https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo={encoded}"
    if deep_link is None:
        return ProductLink(SHOP_HOME, product_id)
    return ProductLink(deep_link, None)
