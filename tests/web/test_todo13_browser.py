"""Real-browser Todo 13 interaction and visual evidence."""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from playwright.async_api import async_playwright, expect
from pydantic import TypeAdapter

from g2b_compare.web.app import create_app
from tests.web.todo13_support import (
    FATAL_RELEASE,
    NO_READY_RELEASE,
    get,
    reader,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.async_api import Browser, Page

EVIDENCE = Path(".omo/evidence/g2b-similar-product-search/todo-13")
APP_JS = Path("src/g2b_compare/web/static/app.js")
WEIGHTS = TypeAdapter(dict[str, list[str]])
BOOLEAN = TypeAdapter(bool)
LOADING_PARTS = (
    "() => {",
    "document.querySelector('#search-form').requestSubmit();",
    "const region=document.querySelector('#results-region');",
    "const status=document.querySelector('.loading-status');",
    "return region.ariaBusy==='true'&&",
    "getComputedStyle(status).display!=='none'&&",
    "status.textContent.trim()==='검색 중';",
    "}",
)
WEIGHT_PARTS = (
    "() => {",
    "const nodes=[...document.querySelectorAll('body *')];",
    "const shown=nodes.filter((node)=>{",
    "const s=getComputedStyle(node),r=node.getBoundingClientRect();",
    "return s.display!=='none'&&s.visibility!=='hidden'&&r.width&&r.height;});",
    "const pseudo=shown.flatMap((node)=>['::before','::after']",
    ".flatMap((kind)=>{const s=getComputedStyle(node,kind);",
    "return s.content==='none'?[]:[s.fontWeight];}));",
    "return {visible:shown.map((node)=>getComputedStyle(node).fontWeight),",
    "pseudo};}",
)
FORM_CONTAINMENT_PARTS = (
    "() => {",
    "const panel=document.querySelector('.search-panel').getBoundingClientRect();",
    "return [...document.querySelectorAll('#search-form input,",
    "#search-form textarea')].every((node)=>{",
    "const box=node.getBoundingClientRect();",
    "return box.left>=panel.left&&box.right<=panel.right;});",
    "}",
)
DOCUMENT_CONTAINMENT = (
    "() => document.documentElement.scrollWidth"
    " <= document.documentElement.clientWidth"
)
TABLE_SCROLL_PARTS = (
    "() => {",
    "const wrap=document.querySelector('.table-wrap');",
    "const headers=[...document.querySelectorAll('th')];",
    "return wrap.scrollWidth>wrap.clientWidth&&",
    "headers.every((node)=>{const style=getComputedStyle(node);",
    "return style.wordBreak==='keep-all'&&style.whiteSpace==='nowrap';});",
    "}",
)
MOBILE_CELL_PARTS = (
    "() => {",
    "const cell=document.querySelector('tbody td');",
    "const row=document.querySelector('tbody tr');",
    "const cells=[...row.querySelectorAll('td')];",
    "const provenance=cell.querySelector('small');",
    "const cellBox=cell.getBoundingClientRect();",
    "const provenanceBox=provenance.getBoundingClientRect();",
    "const pseudo=getComputedStyle(cell,'::before');",
    "const children=[...cell.children];",
    "return pseudo.gridColumnStart==='1'&&",
    "children.every((node)=>getComputedStyle(node).gridColumnStart==='2')&&",
    "cells.every((node)=>node.getBoundingClientRect().height<180)&&",
    "row.getBoundingClientRect().height<650&&",
    "!provenance.textContent.trim().includes('\\n')&&",
    "provenanceBox.left>=cellBox.left&&provenanceBox.right<=cellBox.right;",
    "}",
)


class _BrowserHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        enhanced = self.headers.get("x-requested-with") == "fetch"
        response = anyio.run(_asgi_get, self.path, enhanced)
        self.send_response(response.status_code)
        self.send_header("content-type", response.headers["content-type"])
        self.end_headers()
        _ = self.wfile.write(response.content)


async def _asgi_get(path: str, enhanced: bool) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_app(reader(51)))
    headers = {"X-Requested-With": "fetch"} if enhanced else None
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://browser.test",
    ) as client:
        return await client.get(path, headers=headers)


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BrowserHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    thread.join(5)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_browser_interaction_styles_and_evidence(server_url: str) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        _ = await page.goto(f"{server_url}/?product_name=CCTV")
        await expect(page.locator("tbody tr")).to_have_count(50)
        await _assert_form_contained(page)
        await _assert_document_contained(page)
        loading_expression = "".join(LOADING_PARTS)
        loading = BOOLEAN.validate_python(
            await page.evaluate(loading_expression)
        )
        assert loading is True
        await expect(page.locator("#results-region")).not_to_have_attribute(
            "aria-busy", "true"
        )
        await page.locator(".next-page").click()
        await expect(page).to_have_url(re.compile(r"[?&]page=2(?:&|$)"))
        await expect(page.locator("tbody tr")).to_have_count(1)
        await _assert_computed_weights(page)
        await page.keyboard.press("Tab")
        assert BOOLEAN.validate_python(
            await page.evaluate(
                "() => getComputedStyle(document.activeElement).outlineWidth !== '0px'"
            )
        )
        assert await page.locator("b,strong").count() == 0
        _ = await page.screenshot(
            path=EVIDENCE / "todo13-1440x900.png",
            full_page=False,
        )

        await page.set_viewport_size({"width": 1024, "height": 768})
        _ = await page.goto(f"{server_url}/?product_name=CCTV")
        await _assert_form_contained(page)
        assert BOOLEAN.validate_python(
            await page.evaluate("".join(TABLE_SCROLL_PARTS))
        )
        await _assert_document_contained(page)
        await _assert_computed_weights(page)
        _ = await page.screenshot(
            path=EVIDENCE / "todo13-1024x768.png",
            full_page=False,
        )

        context = await browser.new_context(
            java_script_enabled=False,
            viewport={"width": 375, "height": 812},
        )
        no_js = await context.new_page()
        _ = await no_js.goto(f"{server_url}/?product_name=CCTV")
        await expect(no_js.locator("tbody tr")).to_have_count(50)
        await _assert_document_contained(no_js)
        assert BOOLEAN.validate_python(
            await no_js.evaluate("".join(MOBILE_CELL_PARTS))
        )
        await _assert_computed_weights(no_js)
        await no_js.locator("tbody tr").first.scroll_into_view_if_needed()
        _ = await no_js.screenshot(
            path=EVIDENCE / "todo13-375x812-nojs.png",
            full_page=False,
        )
        await context.close()
        await _assert_loading_excluded(browser)
        await browser.close()


async def _assert_computed_weights(page: Page) -> None:
    expression = "".join(WEIGHT_PARTS)
    weights = WEIGHTS.validate_python(
        await page.evaluate(expression)
    )
    assert set(weights["visible"]) == {"400"}
    assert set(weights["pseudo"]) <= {"400"}


async def _assert_form_contained(page: Page) -> None:
    contained = BOOLEAN.validate_python(
        await page.evaluate("".join(FORM_CONTAINMENT_PARTS))
    )
    assert contained is True


async def _assert_document_contained(page: Page) -> None:
    assert BOOLEAN.validate_python(await page.evaluate(DOCUMENT_CONTAINMENT))


async def _assert_loading_excluded(browser: Browser) -> None:
    responses = (
        await get(reader(0), "/?product_name="),
        await get(reader(0, pin_error=FATAL_RELEASE), "/"),
        await get(reader(0, pin_error=NO_READY_RELEASE), "/"),
    )
    for response in responses:
        page = await browser.new_page()
        await page.set_content(response.text)
        _ = await page.add_script_tag(path=APP_JS)
        busy = BOOLEAN.validate_python(
            await page.evaluate(
                """
                () => {
                    document.querySelector('#search-form').requestSubmit();
                    return document.querySelector(
                        '#results-region'
                    ).ariaBusy === 'true';
                }
                """
            )
        )
        assert busy is False
        await page.close()
