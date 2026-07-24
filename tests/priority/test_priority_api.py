from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_api import crawl_priority_companies
from g2b_compare.priority_models import PriorityCompany, PriorityDataset
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import CatalogPage, ShoppingMallRequest
from g2b_compare.sources.transport import RetryableTransportError

if TYPE_CHECKING:
    from pathlib import Path

    from g2b_compare.sources.shopping_mall import ShoppingMallAdapter


@final
class _TimeoutThenEmptyAdapter:
    calls: int = 0

    def fetch(
        self,
        request: ShoppingMallRequest,
        *,
        service_key: str,
    ) -> CatalogPage:
        _ = service_key
        self.calls += 1
        if self.calls == 1:
            reason = "timeout"
            raise RetryableTransportError(reason, attempts=1)
        return CatalogPage(
            operation=request.operation,
            records=(),
            quarantined=(),
            page_number=1,
            page_size=1000,
            total_count=0,
            request_fingerprint=f"request-{self.calls}",
            raw_response=b"{}",
            content_type="application/json",
        )


def test_api_crawl_skips_timeout_and_preserves_failed_target(tmp_path: Path) -> None:
    store = PriorityStore(tmp_path / "priority.sqlite3")
    store.replace_dataset(
        PriorityDataset(
            companies=(
                PriorityCompany(
                    source_row=1,
                    name="company-a",
                    location="",
                    company_type="",
                    declared_product_count=0,
                    contract_end_date="",
                ),
                PriorityCompany(
                    source_row=2,
                    name="company-b",
                    location="",
                    company_type="",
                    declared_product_count=0,
                    contract_end_date="",
                ),
            ),
            options=(),
        )
    )
    adapter = _TimeoutThenEmptyAdapter()

    result = crawl_priority_companies(
        store,
        cast("ShoppingMallAdapter", cast("object", adapter)),
        "test-key",
        max_calls=6,
    )

    assert adapter.calls == 6
    assert result.calls == 6
    assert result.failures == 1
    assert result.remaining_targets == 1
    remaining = store.crawl_targets((Operation.GET_MAS_CONTRACT_PRODUCT_INFO,))
    assert len(remaining) == 1
    assert remaining[0].company_name == "company-a"
