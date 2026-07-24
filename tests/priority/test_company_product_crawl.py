from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

from g2b_compare.company_product_crawl import (
    crawl_company_products,
    read_company_crawl_report,
)
from g2b_compare.contracts.quota import Operation
from g2b_compare.priority_models import PriorityCompany, PriorityDataset
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import (
    CatalogPage,
    CatalogRecord,
    QuarantinedRecord,
    ShoppingMallRequest,
    SourceIdentity,
    TimestampEvidence,
    TimestampOrigin,
)

if TYPE_CHECKING:
    from pathlib import Path


@final
class _CatalogAdapter:
    calls = 0

    def fetch(
        self,
        request: ShoppingMallRequest,
        *,
        service_key: str,
    ) -> CatalogPage:
        assert service_key == "test-key"
        self.calls += 1
        page_number = int(dict(request.params)["pageNo"])
        if request.operation is Operation.GET_MAS_CONTRACT_PRODUCT_INFO:
            if page_number == 1:
                return _page(
                    request.operation,
                    page_number=1,
                    total_count=3,
                    records=(_record(request.operation, "00000001", "1"),),
                    quarantined=(
                        QuarantinedRecord("missing-stable-source-key", {}),
                    ),
                )
            return _page(
                request.operation,
                page_number=2,
                total_count=3,
                records=(_record(request.operation, "00000002", "2"),),
            )
        return _page(request.operation, page_number=1, total_count=0)


def test_company_crawl_records_every_provider_row_and_reconciles_counts(
    tmp_path: Path,
) -> None:
    store = PriorityStore(tmp_path / "priority.sqlite3")
    store.replace_dataset(
        PriorityDataset(
            companies=(
                PriorityCompany(
                    source_row=1,
                    name="업체 A",
                    location="서울",
                    company_type="일반",
                    declared_product_count=2,
                    contract_end_date="2026-12-31",
                ),
            ),
            options=(),
        )
    )
    store.save_catalog_page(
        company_name="업체 A",
        operation=Operation.GET_MAS_CONTRACT_PRODUCT_INFO,
        page_number=1,
        page_size=1,
        total_count=1,
        records=(_record(Operation.GET_MAS_CONTRACT_PRODUCT_INFO, "00000099", "99"),),
        observed_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    with sqlite3.connect(store.database) as connection:
        _ = connection.execute("DELETE FROM priority_crawl_state")
    adapter = _CatalogAdapter()

    result = crawl_company_products(store, adapter, "test-key", max_calls=10)

    assert result.calls == 4
    assert result.accepted_rows == 2
    assert result.quarantined_rows == 1
    assert result.failures == 0
    assert result.failure_reasons == ()
    assert result.remaining_targets == 0
    assert adapter.calls == 4

    report = read_company_crawl_report(store.database)
    assert len(report) == 1
    company = report[0]
    assert company.company_name == "업체 A"
    assert company.declared_product_count == 2
    assert company.provider_row_count == 3
    assert company.accepted_row_count == 2
    assert company.quarantined_row_count == 1
    assert company.unique_offer_count == 2
    assert company.unique_product_count == 2
    assert company.pending_operation_count == 0
    assert company.provider_mismatch == 0
    assert company.workbook_mismatch == 0
    with sqlite3.connect(store.database) as connection:
        quarantine = connection.execute(
            "SELECT reason, raw_json FROM priority_company_quarantine"
        ).fetchall()
        stale_active = cast(
            "tuple[int] | None",
            connection.execute(
                """
                SELECT active FROM priority_product_offers
                WHERE product_id = '00000099'
                """
            ).fetchone(),
        )
    assert quarantine == [("missing-stable-source-key", "{}")]
    assert stale_active == (0,)


def _page(
    operation: Operation,
    *,
    page_number: int,
    total_count: int,
    records: tuple[CatalogRecord, ...] = (),
    quarantined: tuple[QuarantinedRecord, ...] = (),
) -> CatalogPage:
    return CatalogPage(
        operation=operation,
        records=records,
        quarantined=quarantined,
        page_number=page_number,
        page_size=2,
        total_count=total_count,
        request_fingerprint=f"{operation}-{page_number}",
        raw_response=b"{}",
        content_type="application/json",
    )


def _record(
    operation: Operation,
    product_id: str,
    contract_sequence: str,
) -> CatalogRecord:
    observed_at = datetime(2026, 7, 21, tzinfo=UTC)
    return CatalogRecord(
        identity=SourceIdentity(operation, ("CONTRACT", contract_sequence)),
        product_id=product_id,
        classification_number="10000000",
        category_name="본품",
        detail_category_number="10000001",
        spec_name=f"규격 {product_id}",
        contract_price="1000",
        image_url=f"https://example.test/{product_id}.jpg",
        timestamp=TimestampEvidence(
            observed_at.isoformat(),
            TimestampOrigin.OBSERVED_AT_FALLBACK,
            0,
        ),
        raw_fields={
            "cntrctCorpNm": "업체 A",
            "prdctUnit": "개",
            "cntrctMthdNm": "다수공급자계약",
        },
    )
