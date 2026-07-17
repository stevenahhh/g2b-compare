"""Define strict request, response, error, and pinned-reader contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import (
    TYPE_CHECKING,
    Annotated,
    ClassVar,
    Final,
    Literal,
    Protocol,
    Self,
    override,
)

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

if TYPE_CHECKING:
    from .comparators import ComparatorView, ProductRecord, ScoredRecord
    from .release_models import ReleasePin

INVALID_PRICE: Final = "invalid_price_constraint"
QUERY_TOO_LONG: Final = "query_too_long"
INVALID_QUERY: Final = "invalid_query"
PAGE_OVERFLOW: Final = "page_overflow"
PRICE_REQUIRES_TARGET: Final = "price_requires_target"
TOLERANCE_REQUIRES_TARGET: Final = "tolerance_requires_target"
DETAIL_REQUIRES_CATEGORY: Final = "detail_requires_category"
MAX_TOLERANCE: Final = Decimal(100)

type JsonValue = (
    str
    | int
    | float
    | bool
    | Decimal
    | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)


def _price(value: JsonValue) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise PydanticCustomError(INVALID_PRICE, INVALID_PRICE)
    return value


def _tolerance(value: JsonValue) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (bool, list, dict, float)):
        raise PydanticCustomError(INVALID_PRICE, INVALID_PRICE)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise PydanticCustomError(INVALID_PRICE, INVALID_PRICE) from error
    if not parsed.is_finite() or parsed < 0 or parsed > MAX_TOLERANCE:
        raise PydanticCustomError(INVALID_PRICE, INVALID_PRICE)
    return parsed


type PositivePrice = Annotated[int | None, BeforeValidator(_price)]
type Tolerance = Annotated[Decimal | None, BeforeValidator(_tolerance)]


class SearchRequest(BaseModel):
    """Parse the strict public search request before any release read."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    product_name: str
    category_code: str | None = None
    detail_category_code: str | None = None
    spec_text: str = ""
    target_price_won: PositivePrice = None
    price_unit: str | None = None
    price_tolerance_pct: Tolerance = None
    page: int = 1
    page_size: Literal[50] = 50

    @field_validator("product_name", "spec_text")
    @classmethod
    def _query_lengths(cls, value: str, info: ValidationInfo) -> str:
        maximum = 100 if info.field_name == "product_name" else 500
        if len(value) > maximum:
            raise PydanticCustomError(QUERY_TOO_LONG, QUERY_TOO_LONG)
        if info.field_name == "product_name" and not value:
            raise PydanticCustomError(INVALID_QUERY, INVALID_QUERY)
        return value

    @field_validator("page")
    @classmethod
    def _positive_page(cls, value: int) -> int:
        if value < 1:
            raise PydanticCustomError(PAGE_OVERFLOW, PAGE_OVERFLOW)
        return value

    @model_validator(mode="after")
    def _cross_fields(self) -> Self:
        if self.target_price_won is None and self.price_unit is not None:
            raise PydanticCustomError(PRICE_REQUIRES_TARGET, PRICE_REQUIRES_TARGET)
        if self.target_price_won is None and self.price_tolerance_pct is not None:
            raise PydanticCustomError(
                TOLERANCE_REQUIRES_TARGET, TOLERANCE_REQUIRES_TARGET
            )
        if self.category_code is None and self.detail_category_code is not None:
            raise PydanticCustomError(
                DETAIL_REQUIRES_CATEGORY, DETAIL_REQUIRES_CATEGORY
            )
        return self


@dataclass(frozen=True, slots=True)
class CategoryRef:
    """One known upper/detail ownership tuple."""

    upper_code: str
    detail_code: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One paginated product with query and product-anchored comparisons."""

    product: ProductRecord
    scores: ScoredRecord
    within_price_tolerance: bool | None
    comparators: tuple[ComparatorView, ComparatorView, ComparatorView]


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Typed response for both cached and uncached service paths."""

    status: Literal["ok", "no-matches"]
    release: ReleasePin
    selected_category: CategoryRef | None
    selected_price_unit: str | None
    price_tolerance_pct: Decimal | None
    total_results: int
    page: int
    page_size: Literal[50]
    results: tuple[SearchResult, ...]


@dataclass(frozen=True, slots=True)
class SearchServiceError(Exception):
    """Return one stable semantic error with deterministic choices."""

    code: str
    choices: tuple[str, ...] = ()

    @override
    def __str__(self) -> str:
        return self.code


class SearchReader(Protocol):
    """Read only through coordinates pinned at request start."""

    def pin_active_release(self) -> ReleasePin:
        """Pin the ready bundle and attempt exactly once."""
        ...

    def is_stale(self, pin: ReleasePin) -> bool:
        """Project freshness without changing the release identity."""
        ...

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        """Read the pinned release category ownership tuples."""
        ...

    def exact_products(
        self, pin: ReleasePin, product_name: str
    ) -> tuple[ProductRecord, ...]:
        """Read active exact-name products from the pinned materialization."""
        ...

    def cached_comparators(
        self, pin: ReleasePin, anchor_id: str
    ) -> tuple[ComparatorView, ...] | None:
        """Read only the pinned ready-attempt comparator rows."""
        ...
