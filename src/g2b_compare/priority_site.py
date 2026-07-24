"""Browser collector for verified main-product to option relations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from g2b_compare.priority_models import ProductOptionRelation

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from g2b_compare.priority_store import PriorityStore

HOME: Final = "https://shop.g2b.go.kr/"
SEARCH_OPEN: Final = "#mf_wfm_gnb_wfm_gnbBtm_btnMtSrch"
SEARCH_TYPE: Final = "#mf_wfm_gnb_wfm_gnbBtm_sbxSelectValue_input_0"
SEARCH_INPUT: Final = "#mf_wfm_gnb_wfm_gnbBtm_ibxSrchKeyword"
SEARCH_BUTTON: Final = "#mf_wfm_gnb_wfm_gnbBtm_btnSrch"
RESULT_THUMB: Final = '[id$="_genLstGdsList_0_thumb"]'
OPTION_ID: Final = re.compile(r"\[(\d{8})\]")
OPTION_PRICE: Final = re.compile(r":\s*([\d,]+)\s*$")


@dataclass(frozen=True, slots=True)
class SiteCrawlResult:
    """Counts from one browser relation crawl."""

    inspected: int
    relations: int
    failed: int


def parse_option_label(label: str) -> tuple[str, str, int] | None:
    """Extract one option identity and displayed price from a select label."""
    identity = OPTION_ID.search(label)
    if identity is None:
        return None
    price_match = OPTION_PRICE.search(label)
    price = int(price_match.group(1).replace(",", "")) if price_match else 0
    return identity.group(1), label.strip(), price


def crawl_product_options(
    store: PriorityStore,
    *,
    max_items: int = 0,
    headless: bool = True,
) -> SiteCrawlResult:
    """Inspect uncrawled products and persist relations verified on detail pages."""
    targets = store.pending_site_products(max_items)
    inspected = 0
    relation_count = 0
    failed = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page(locale="ko-KR")
        for product_id in targets:
            try:
                options = _read_options(page, product_id)
            except PlaywrightTimeoutError:
                store.save_site_result(product_id, (), status="retry")
                failed += 1
            else:
                store.save_site_result(product_id, options, status="complete")
                relation_count += len(options)
            inspected += 1
        browser.close()
    return SiteCrawlResult(inspected, relation_count, failed)


def _read_options(page: Page, product_id: str) -> tuple[ProductOptionRelation, ...]:
    _ = page.goto(HOME, wait_until="domcontentloaded", timeout=30_000)
    page.locator(SEARCH_OPEN).click(timeout=15_000)
    _ = page.locator(SEARCH_TYPE).select_option(label="물품식별번호")
    page.locator(SEARCH_INPUT).fill(product_id)
    page.locator(SEARCH_BUTTON).click()
    page.locator(RESULT_THUMB).first.click(timeout=15_000)
    page.get_by_text(f"물품식별번호{product_id}", exact=False).wait_for(timeout=15_000)
    selector = page.get_by_role("combobox", name="추가할 상품을 선택하세요")
    if selector.count() == 0:
        return ()
    labels = selector.locator("option").all_text_contents()
    parsed = (parse_option_label(text) for text in labels)
    return tuple(
        ProductOptionRelation(
            kind="additional",
            product_id=item[0],
            raw_label=item[1],
            price_won=item[2],
        )
        for item in parsed
        if item is not None
    )
