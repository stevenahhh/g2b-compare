from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from playwright.async_api import Route, async_playwright, expect

from g2b_compare.priority_models import PriorityCompany, PriorityDataset, PriorityOption
from g2b_compare.priority_store import PriorityStore
from g2b_compare.web.app import create_app

PRIORITY_TEMPLATE = Path("src/g2b_compare/web/templates/priority.html")
PRIORITY_SCRIPT = Path("src/g2b_compare/web/static/priority.js")
PRIORITY_CSS = Path("src/g2b_compare/web/static/mvp.css")

@pytest.mark.asyncio
async def test_priority_page_uses_procurement_line_columns_and_paginates(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    app = create_app(database=database, home=tmp_path)
    store = PriorityStore(database)
    store.replace_dataset(
        PriorityDataset(
            companies=(
                PriorityCompany(
                    source_row=6,
                    name="주식회사 홍석",
                    location="전남",
                    company_type="중소기업",
                    declared_product_count=31,
                    contract_end_date="2026-11-07",
                ),
            ),
            options=tuple(
                PriorityOption(
                    source_row=row,
                    company_name="주식회사 홍석",
                    kind="추가선택",
                    product_id=f"22{row:06d}",
                    item_name="카메라브래킷",
                    spec=f"규격 {row}",
                    price_won=1000 + row,
                    details="",
                )
                for row in range(3, 94)
            )
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/priority", params={"q": "없는 검색어", "page": "1"})
        second_page = await client.get("/priority", params={"q": "없는 검색어", "page": "2"})
        third_page = await client.get("/priority", params={"q": "없는 검색어", "page": "3"})
        fourth_page = await client.get("/priority", params={"q": "없는 검색어", "page": "4"})

    assert response.status_code == 200
    assert response.text.count('class="line-item"') == 30
    assert "G2B식별번호" in response.text
    assert "본품/옵션" in response.text
    assert '<script src="/static/priority.js" defer></script>' in response.text
    assert 'class="pagination"' not in response.text
    assert 'value="없는 검색어"' in response.text

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.add_init_script(
            """Object.defineProperty(window, "localStorage", {
              configurable: true,
              get() { throw new DOMException("Denied", "SecurityError"); },
            });"""
        )

        async def serve_priority(route: Route) -> None:
            page_number = route.request.url.split("page=")[-1] if "page=" in route.request.url else "1"
            body = {
                "1": response.text,
                "2": second_page.text,
                "3": third_page.text,
                "4": fourth_page.text,
            }[page_number]
            await route.fulfill(status=200, content_type="text/html", body=body)

        await page.route("**/priority*", serve_priority)
        await page.route(
            "**/static/mvp.css",
            lambda route: route.fulfill(
                content_type="text/css",
                body=Path("src/g2b_compare/web/static/mvp.css").read_text(encoding="utf-8"),
            ),
        )
        await page.route(
            "**/static/priority.js",
            lambda route: route.fulfill(
                content_type="application/javascript",
                body=PRIORITY_SCRIPT.read_text(encoding="utf-8"),
            ),
        )
        await page.goto("http://test/priority?q=없는%20검색어")
        await expect(page.locator(".line-item")).to_have_count(30)
        await page.locator("#q").fill("홍석")
        assert await page.locator("mark.search-highlight").count() == 30
        await page.locator("#q").fill("카메라")
        assert await page.locator("mark.search-highlight").count() == 30
        await page.locator("[data-theme-toggle]").click()
        assert (
            await page.locator("html").get_attribute("data-theme") == "dark"
        )
        for _ in range(3):
            await page.locator(".priority-virtual-scroll").evaluate(
                "node => { node.scrollTop = node.scrollHeight; "
                "node.dispatchEvent(new Event('scroll')); }"
            )
            await page.wait_for_timeout(50)
        await expect(page.locator(".priority-loader")).to_have_text(
            "모든 결과를 불러옴"
        )
        virtual_rows = await page.evaluate(
            """() => {
              const px = (selector) => parseFloat(
                document.querySelector(selector).firstElementChild
                  .firstElementChild.style.height || "0"
              ) / 56;
              return document.querySelectorAll(".line-item").length
                + px(".priority-spacer-top")
                + px(".priority-spacer-bottom");
            }"""
        )
        assert virtual_rows == 91
        assert await page.locator(".line-item").count() <= 60
        await page.goto("http://test/priority?page=2")
        await expect(page.locator(".priority-loader")).to_have_text(
            "아래로 스크롤하면 다음 결과를 불러옴"
        )
        await expect(page.locator('.line-item[aria-rowindex="2"]')).to_have_count(1)
        await browser.close()

def test_priority_virtual_list_is_bounded_and_search_only_highlights() -> None:
    template = PRIORITY_TEMPLATE.read_text(encoding="utf-8")
    script = PRIORITY_SCRIPT.read_text(encoding="utf-8")
    css = PRIORITY_CSS.read_text(encoding="utf-8")

    assert "priority-virtual-scroll" in template
    assert "priority-results-body" in template
    assert 'role="region"' in template
    assert 'aria-rowcount="{{ result.total_count + 1 }}"' in template
    assert 'aria-rowindex="{{ (result.page - 1) * 30 + loop.index + 1 }}"' in template
    assert 'item.detail_url.lower().startswith(("http://", "https://"))' in template
    assert "PAGE_SIZE = 30" not in script
    assert "WINDOW_SIZE = 60" in script
    assert "OVERSCAN_ROWS = 8" in script
    assert "loadedItems.push(...rows)" in script
    assert "body.replaceChildren(fragment)" in script
    assert 'form.addEventListener("submit", (event) => event.preventDefault())' in script
    assert 'mark.className = "search-highlight"' in script
    assert "THEME_KEY = \"g2b-theme\"" in script
    assert "readTheme" in script
    assert "writeTheme" in script
    assert "localStorage.setItem(THEME_KEY, theme)" in script
    assert "row.normalize()" in script
    assert "fetch(`/priority?page=${page}`)" in script
    assert "loadPreviousPages" in script
    assert ".priority-results-body .line-item td" in css
    assert "white-space: nowrap;" in css
