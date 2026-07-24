"""Pool one product name's currently active offers directly from the live API."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.contracts.quota import Operation
from g2b_compare.materialize.prices import ComparisonPrice
from g2b_compare.normalize.text import normalize_text
from g2b_compare.ranking.topk import RankableProduct
from g2b_compare.services.comparator_models import ProductRecord
from g2b_compare.services.search_models import CategoryRef
from g2b_compare.sources.shopping_mall import ShoppingMallRequest

if TYPE_CHECKING:
    from datetime import datetime

    from g2b_compare.sources.shopping_mall import CatalogRecord, ShoppingMallAdapter

CONTRACT_OPERATIONS: Final = (
    Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
    Operation.GET_UNIT_CONTRACT_PRODUCT_INFO,
    Operation.GET_THIRD_PARTY_UNIT_CONTRACT_PRODUCT_INFO,
)
PAGE_SIZE: Final = 10


@dataclass(frozen=True, slots=True)
class LivePool:
    """Deduplicated current-offer products observed for one product name."""

    products: tuple[ProductRecord, ...]
    categories: tuple[CategoryRef, ...]
    has_next: bool

    @property
    def truncated(self) -> bool:
        """Retain the prior signal name for callers that only need more-results state."""
        return self.has_next


@dataclass(frozen=True, slots=True)
class _FetchContext:
    """Fixed dispatch context shared by every page request in one search."""

    adapter: ShoppingMallAdapter
    service_key: str
    observed_at: datetime


def fetch_live_pool(
    adapter: ShoppingMallAdapter,
    service_key: str,
    product_name: str,
    observed_at: datetime,
    *,
    source_page: int = 1,
) -> LivePool:
    """Fetch one provider page per contract operation and merge current records."""
    context = _FetchContext(adapter, service_key, observed_at)
    name_key = normalize_text(product_name).derived
    with ThreadPoolExecutor(max_workers=len(CONTRACT_OPERATIONS)) as executor:
        futures = [
            executor.submit(
                _collect_operation,
                context,
                operation,
                product_name,
                source_page,
            )
            for operation in CONTRACT_OPERATIONS
        ]
        collected = [future.result() for future in futures]
    by_product: dict[str, list[CatalogRecord]] = {}
    has_next = False
    for records, operation_has_next in collected:
        has_next = has_next or operation_has_next
        for record in records:
            if not _is_current(record, observed_at):
                continue
            by_product.setdefault(record.product_id, []).append(record)
    products = tuple(
        _merge_product(records)
        for records in by_product.values()
        if normalize_text(records[0].category_name).derived == name_key
    )
    categories = tuple(
        CategoryRef(*pair)
        for pair in sorted(
            {item.rankable.category_key for item in products},
            key=lambda pair: (pair[0].encode(), pair[1].encode()),
        )
    )
    return LivePool(products, categories, has_next)


def _collect_operation(
    context: _FetchContext,
    operation: Operation,
    product_name: str,
    page_no: int,
) -> tuple[list[CatalogRecord], bool]:
    """Fetch one operation page in isolation, safe for a worker thread."""
    page = context.adapter.fetch(
        ShoppingMallRequest(
            operation,
            (
                ("type", "json"),
                ("pageNo", str(page_no)),
                ("numOfRows", str(PAGE_SIZE)),
                ("prdctClsfcNoNm", product_name),
            ),
            context.observed_at,
        ),
        service_key=context.service_key,
    )
    return list(page.records), page_no * PAGE_SIZE < page.total_count


def _merge_product(records: list[CatalogRecord]) -> ProductRecord:
    selected = max(records, key=_record_recency)
    return ProductRecord(
        rankable=RankableProduct(
            product_id=selected.product_id,
            category_key=(
                selected.classification_number,
                selected.detail_category_number,
            ),
            product_name_key=normalize_text(selected.category_name).derived,
            option_text=normalize_text(selected.spec_name).derived,
            active=True,
            price=_comparison_price(selected),
        ),
        product_name_raw=selected.category_name,
        data_as_of=selected.timestamp.value,
        attribute_coverage="live",
        spec_name_raw=selected.spec_name,
        image_url=selected.image_url,
        contract_item_key="_".join(selected.identity.stable_source_key),
        supplier_name=_field(selected, "cntrctCorpNm"),
        contract_method=_field(selected, "cntrctMthdNm"),
        delivery_condition=_field(selected, "prdctDlvryCndtnNm"),
        purchase_type=_field(selected, "levDivNm"),
    )


def _comparison_price(record: CatalogRecord) -> ComparisonPrice:
    raw_amount = record.contract_price.replace(",", "").strip()
    raw_unit = _field(record, "prdctUnit")
    if not raw_amount or not raw_unit:
        return _inactive_price()
    try:
        amount = int(raw_amount)
    except ValueError:
        return _inactive_price()
    if amount <= 0:
        return _inactive_price()
    unit_key = normalize_text(raw_unit).derived
    if not unit_key:
        return _inactive_price()
    return ComparisonPrice(
        active=True,
        amount_won=amount,
        unit_key=unit_key,
        offer_key=None,
        reason=None,
    )


def _inactive_price() -> ComparisonPrice:
    return ComparisonPrice(
        active=False,
        amount_won=None,
        unit_key=None,
        offer_key=None,
        reason="no-active-offer",
    )


def _record_recency(record: CatalogRecord) -> tuple[str, tuple[str, str]]:
    digits = "".join(
        character for character in record.timestamp.value if character.isdigit()
    )
    return digits, record.identity.stable_source_key


def _is_current(record: CatalogRecord, observed_at: datetime) -> bool:
    today = observed_at.strftime("%Y%m%d")
    starts = _date_value(_field(record, "cntrctBgnDate"))
    ends = _date_value(_field(record, "cntrctEndDate"))
    return (starts is None or starts <= today) and (ends is None or ends >= today)


def _date_value(raw: str) -> str | None:
    digits = "".join(character for character in raw if character.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def _field(record: CatalogRecord, key: str) -> str:
    value = record.raw_fields.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""
