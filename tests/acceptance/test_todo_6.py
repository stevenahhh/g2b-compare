from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from g2b_compare.sources.thing_list import AttributeRequest
from g2b_compare.sync.attribute_queue import (
    CatalogAttributeInput,
    QueuePlanningInput,
    QuotaWindow,
    dispatch_budget,
    plan_attribute_queue,
)
from tests.sources.test_thing_list import (
    ResponseStub,
    attribute_adapter,
    attribute_body,
    attribute_manifest,
)


def test_happy(tmp_path: Path) -> None:
    adapter, _requester = attribute_adapter(
        tmp_path, ResponseStub(200, attribute_body())
    )
    page = adapter.fetch_page(AttributeRequest(3, "22065235", 1, 10))
    products = tuple(
        CatalogAttributeInput(f"P-{index:04d}", index % 3, f"{index:064x}")
        for index in range(1001)
    )
    plan = plan_attribute_queue(
        QueuePlanningInput(3, products, (), datetime(2026, 7, 16, tzinfo=UTC))
    )
    budget = dispatch_budget(QuotaWindow(attribute_manifest(), 0, 0))
    assert len(page.records) == 1
    assert len(plan.dispatchable(budget)) == 900
    assert "runtime-only" not in json.dumps(page.records[0].raw_fields_json)
