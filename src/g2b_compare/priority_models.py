"""Typed rows used by the priority collection database."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class PriorityCompany(_FrozenModel):
    """One company from the priority workbook."""

    source_row: int = Field(ge=1)
    name: str = Field(min_length=1)
    location: str
    company_type: str
    declared_product_count: int = Field(ge=0)
    contract_end_date: str


class PriorityOption(_FrozenModel):
    """One unmodified logical option row from the priority workbook."""

    source_row: int = Field(ge=1)
    company_name: str = Field(min_length=1)
    kind: Literal["추가선택", "선택부품"]
    product_id: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    spec: str
    price_won: int = Field(ge=0)
    details: str


class PriorityDataset(_FrozenModel):
    """Workbook rows ready for one transactional import."""

    companies: tuple[PriorityCompany, ...]
    options: tuple[PriorityOption, ...]


class ProductOptionTarget(_FrozenModel):
    """One main product whose official child dropdowns need collection."""

    product_id: str = Field(pattern=r"^\d{8}$")
    contract_item_number: str = Field(min_length=1)
    contract_group: str = Field(min_length=1)


class ProductOptionRelation(_FrozenModel):
    """One official additional-item or component relation."""

    kind: Literal["additional", "component"]
    product_id: str = Field(pattern=r"^\d{8}$")
    raw_label: str = Field(min_length=1)
    price_won: int = Field(ge=0)


class CrawlTarget(_FrozenModel):
    """One resumable company and operation cursor."""

    company_name: str
    location: str
    operation: str
    next_page: int = Field(ge=1)


class PriorityStatus(_FrozenModel):
    """Counts shown by the CLI and debug UI."""

    company_count: int
    option_row_count: int
    unique_option_count: int
    product_count: int
    relation_count: int
    pending_api_target_count: int
    pending_site_product_count: int


class PriorityLineSort(StrEnum):
    """Supported catalog sort orders."""

    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NAME_ASC = "name_asc"
    PRODUCT_ID_ASC = "product_id_asc"


class PriorityLine(_FrozenModel):
    """One procurement-estimate style web row."""

    path: str
    item_name: str
    spec: str
    unit: str
    price_won: int
    product_id: str
    contract_method: str
    delivery_condition: str
    delivery_days: str
    contract_end_date: str
    company_name: str
    detail_url: str
    source_kind: str
    relation_id: str | None = None


class PriorityLinePage(_FrozenModel):
    """One 30-row page and its navigation facts."""

    items: tuple[PriorityLine, ...]
    page: int
    page_count: int
    total_count: int


class ProductAttribute(_FrozenModel):
    """One product attribute displayed from the collected catalog payload."""

    name: str
    value: str
    unit: str = ""


class CatalogProduct(_FrozenModel):
    """One main-product card in the desktop catalog."""

    item_name: str
    spec: str
    unit: str
    price_won: int
    product_id: str
    contract_method: str
    delivery_condition: str
    delivery_days: str
    contract_end_date: str
    company_name: str
    detail_url: str
    image_url: str
    attributes: tuple[ProductAttribute, ...]


class CatalogProductPage(_FrozenModel):
    """One pageable main-product result."""

    items: tuple[CatalogProduct, ...]
    page: int
    page_count: int
    total_count: int


class CatalogOption(_FrozenModel):
    """One verified child option shown beside its parent product."""

    parent_product_id: str
    item_name: str
    relation_kind: Literal["additional", "component"]
    image_url: str
    spec: str
    unit: str
    price_won: int
    product_id: str
    company_name: str
    detail_url: str
    relation_id: str
