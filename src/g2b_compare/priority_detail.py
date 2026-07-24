"""Public Shopping Mall detail-option response adapter."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol, final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from g2b_compare.priority_models import ProductOptionRelation, ProductOptionTarget
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonValue

DETAIL_URL: Final = (
    "https://shop.g2b.go.kr/gm/gms/gmsf/GdsDtlInfo/selectPdctBaseInfo.do"
)
REQUEST_FAILURE: Final = "shopping-detail-request"
RESPONSE_FAILURE: Final = "shopping-detail-response"


class _DetailRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    product_id: str = Field(alias="itemIdnfNo", pattern=r"^\d{8}$")
    item_name: str = Field(alias="ntslItemNm", min_length=1)
    purchase_kind: str = Field(alias="prchsMthdSeNm", min_length=1)
    price_won: int = Field(alias="dscntAplcnUprc", ge=0)


class _DetailEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    rows: tuple[_DetailRow, ...] = Field(default=(), alias="dlCtrtOptnItmltL")
    error_code: int = Field(default=0, alias="ErrorCode")


class ProductDetailAdapter(Protocol):
    """Official detail-option capability consumed by the batch crawler."""

    def fetch(self, target: ProductOptionTarget) -> tuple[ProductOptionRelation, ...]:
        """Fetch both child dropdowns for one contract group."""
        ...


@final
@dataclass(frozen=True, slots=True)
class HttpProductDetailAdapter:
    """HTTP adapter for the keyless public product-detail endpoint."""

    client: httpx.Client

    def fetch(self, target: ProductOptionTarget) -> tuple[ProductOptionRelation, ...]:
        """Fetch and parse both official option dropdowns."""
        try:
            response = self.client.post(
                DETAIL_URL,
                headers={"Accept": "application/json", "Referer": "https://shop.g2b.go.kr/"},
                json={"dlGdsDtlInfoSrchM": _search(target.contract_item_number)},
            )
            _ = response.raise_for_status()
            envelope = _DetailEnvelope.model_validate_json(response.content)
            relations = _relations(envelope)
        except (httpx.HTTPError, ValueError) as error:
            raise RetryableTransportError(REQUEST_FAILURE, attempts=1) from error
        return relations


def parse_detail_options(payload: JsonValue) -> tuple[ProductOptionRelation, ...]:
    """Parse only additional-item and component rows from one detail response."""
    envelope = _DetailEnvelope.model_validate(payload)
    return _relations(envelope)


def _relations(
    envelope: _DetailEnvelope,
) -> tuple[ProductOptionRelation, ...]:
    if envelope.error_code != 0:
        raise RetryableTransportError(RESPONSE_FAILURE, attempts=1)
    relations: list[ProductOptionRelation] = []
    for row in envelope.rows:
        kind = _kind(row.purchase_kind)
        if kind is None:
            continue
        name = html.unescape(row.item_name)
        relations.append(
            ProductOptionRelation(
                kind=kind,
                product_id=row.product_id,
                raw_label=(
                    f"[{row.purchase_kind}] [{row.product_id}] {name} : "
                    f"{row.price_won:,}"
                ),
                price_won=row.price_won,
            )
        )
    return tuple(relations)


def _kind(value: str) -> Literal["additional", "component"] | None:
    if value == "별도구매":
        return "additional"
    if value == "선택부품":
        return "component"
    return None


def _search(contract_item_number: str) -> dict[str, JsonValue]:
    return {
        "srchCtrtItemMngNo": contract_item_number,
        "srchCtrtNo": "",
        "srchCtrtChgOrd": "",
        "srchCtrtItemSqno": "",
        "srchItemIdnfNo": "",
        "recordCountPerPage": "",
        "currentPage": "",
        "srchParam1": "",
        "srchEtpsUntyGrpNo": "",
        "srchCgryLCd": "",
        "srchCgryMCd": "",
        "srchDtlsPrnmNo": "",
        "srchPrcmBsneDtlAreaCd": "",
        "srchCtrtTyCd": "",
        "fromDate": "",
        "toDate": "",
    }
