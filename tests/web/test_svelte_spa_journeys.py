"""Task 13 production-bundle browser journeys."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

from openpyxl import Workbook, load_workbook
import pytest
import uvicorn
from playwright.async_api import BrowserContext, Page, Route, async_playwright, expect

from g2b_compare.web import app as app_module

DIST = Path("src/g2b_compare/web/frontend_dist")
EVIDENCE = Path(".omo/evidence/svelte-spa-single-user")


@pytest.fixture(scope="module")
def spa_url() -> Iterator[str]:
    assert (DIST / "index.html").is_file(), "production SPA bundle is required"
    with TemporaryDirectory() as temporary:
        home = Path(temporary)
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(app_module, "FRONTEND_DIST", DIST)
            monkeypatch.setenv("G2B_SERVE_SPA", "1")
            app = app_module.create_app(database=home / "g2b.sqlite3", home=home)
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False)
            )
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("FastAPI SPA server did not start")
            socket = next(iter(server.servers)).sockets[0]
            try:
                yield f"http://127.0.0.1:{socket.getsockname()[1]}"
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                assert not thread.is_alive()


def _product(number: int = 1) -> dict[str, object]:
    return {
        "product_id": f"{number:08d}",
        "name": "실외형 네트워크 카메라" if number == 1 else f"보조 카메라 {number}",
        "spec": "4K · IP66",
        "unit": "대",
        "price_won": 1_250_000,
        "company_name": "주식회사 화면",
        "contract_method": "다수공급자계약",
        "delivery_condition": "현장설치도",
        "delivery_days": "14",
        "contract_end_date": "2027-12-31",
        "detail_url": "https://example.test/detail/main",
        "g2b_url": "https://example.test/g2b/main",
        "image_url": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='92' height='92'%3E%3Crect width='92' height='92' fill='%230369a1'/%3E%3C/svg%3E",
        "attributes": [{"name": "해상도", "value": "3840×2160", "unit": "px"}, {"name": "방수", "value": "IP66", "unit": ""}],
    }


def _option() -> dict[str, object]:
    return {
        "parent_product_id": "00000001",
        "relation_id": "REL-PTZ-01",
        "product_id": "00000002",
        "name": "PTZ 추가 선택품목",
        "spec": "30배 광학 줌",
        "unit": "식",
        "price_won": 350_000,
        "company_name": "주식회사 옵션",
        "detail_url": "https://example.test/detail/option",
        "g2b_url": "https://example.test/g2b/option",
        "attributes": [{"name": "광학줌", "value": "30", "unit": "배"}],
    }


def _comparison(line: dict[str, object], slot: str) -> dict[str, object]:
    suffix = {"A": "알파", "B": "베타", "C": "감마"}[slot]
    return {
        "slot": slot,
        "product_id": line["product_id"],
        "relation_id": line.get("relation_id"),
        "company_snapshot": f"비교{suffix}",
        "spec_snapshot": f"{line['spec_snapshot']} {suffix}",
        "price_won_snapshot": int(line["unit_price_won_snapshot"]) + {"A": 0, "B": 1000, "C": 2000}[slot],
        "attributes": [{"name": "비교속성", "value": suffix, "unit": ""}],
    }


def _remote_estimate(estimate_id: str, payload: dict[str, object]) -> dict[str, object]:
    lines = []
    for position, source in enumerate(payload["lines"], start=1):
        line = dict(source)
        line.update(
            {
                "line_no": position,
                "quantity": str(line["quantity"]),
                "attributes": _product()["attributes"] if line["line_kind"] == "main" else _option()["attributes"],
                "comparisons": [_comparison(line, slot) for slot in ("A", "B", "C")],
            }
        )
        lines.append(line)
    return {
        "id": estimate_id,
        "title": payload["title"],
        "created_at": "2026-07-22T10:00:00+00:00",
        "updated_at": "2026-07-22T10:00:01+00:00",
        "lines": lines,
        "export_ready": True,
    }


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "관급내역"
    sheet.append(["품명", "수량", "금액"])
    sheet.append(["실외형 네트워크 카메라", 1, 1_250_000])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


async def _activate_service_worker(page: Page) -> None:
    await page.evaluate("() => navigator.serviceWorker.ready")
    await page.reload(wait_until="networkidle")
    assert await page.evaluate("() => Boolean(navigator.serviceWorker.controller)")




async def _install_contract_routes(
    page: Page,
    estimates: dict[str, dict[str, object]],
    counters: dict[str, Counter[str]],
    offline: dict[str, bool],
    *,
    total_count: int = 90,
) -> None:
    async def api(route: Route) -> None:
        request = route.request
        path = urlparse(request.url).path
        if offline["enabled"]:
            await route.abort("failed")
            return
        counters[request.method][path] += 1
        if path == "/api/catalog/products" and request.method == "GET":
            query = parse_qs(urlparse(request.url).query)
            page_number = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["30"])[0])
            page_count = max(1, -(-total_count // page_size))
            first = (page_number - 1) * page_size + 1
            items = [_product(number) for number in range(first, min(first + page_size, total_count + 1))]
            await route.fulfill(json={"items": items, "page": page_number, "page_count": page_count, "total_count": total_count})
            return
        if path == "/api/catalog/products/00000001/options" and request.method == "GET":
            await route.fulfill(json={"items": [_option()], "page": 1, "page_count": 1, "total_count": 1})
            return
        if path == "/api/estimates" and request.method == "GET":
            await route.fulfill(json=[{"id": estimate_id, "title": document["title"], "updated_at": "2026-07-22T10:00:01+00:00", "line_count": len(document["lines"])} for estimate_id, document in estimates.items()])
            return
        if path.startswith("/api/estimates/"):
            estimate_id = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                estimates[estimate_id] = json.loads(request.post_data or "{}")
                await route.fulfill(status=200, json=_remote_estimate(estimate_id, estimates[estimate_id]))
                return
            if request.method == "DELETE":
                estimates.pop(estimate_id, None)
                await route.fulfill(status=204, body="")
                return
            if request.method == "GET" and estimate_id in estimates:
                await route.fulfill(json=_remote_estimate(estimate_id, estimates[estimate_id]))
                return
        await route.fulfill(status=404, json={"detail": "unhandled test contract"})

    await page.route("**/api/**", api)


async def _read_estimates(page: Page) -> list[dict[str, object]]:
    return await page.evaluate(
        """() => new Promise((resolve, reject) => {
          const open = indexedDB.open('g2b-spa', 1);
          open.onerror = () => reject(open.error);
          open.onsuccess = () => {
            const tx = open.result.transaction('estimates', 'readonly');
            const get = tx.objectStore('estimates').getAll();
            get.onerror = () => reject(get.error);
            get.onsuccess = () => resolve(get.result);
          };
        })"""
    )


async def _wait_for_server_lines(
    estimates: dict[str, dict[str, object]], line_count: int
) -> None:
    for _ in range(100):
        if any(len(document["lines"]) >= line_count for document in estimates.values()):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"server did not receive an estimate with {line_count} lines")



@pytest.mark.asyncio
async def test_svelte_spa_catalog_to_comparison_journey(spa_url: str) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    estimates: dict[str, dict[str, object]] = {}
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    offline = {"enabled": False}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = await context.new_page()
        await _install_contract_routes(page, estimates, counters, offline)
        await page.goto(spa_url, wait_until="networkidle")
        await page.get_by_role("button", name="다크 모드").click()
        assert await page.locator("html").get_attribute("data-theme") == "dark"
        await page.reload(wait_until="networkidle")
        assert await page.locator("html").get_attribute("data-theme") == "dark"
        await expect(page.get_by_role("button", name="라이트 모드")).to_be_visible()
        await expect(page.get_by_text("실외형 네트워크 카메라").first).to_be_visible()
        assert await page.locator(".catalog-card").count() > 0
        assert await page.locator(".catalog-card").count() <= 60
        assert await page.locator(".g2b-link").first.evaluate("node => getComputedStyle(node).width") == "150px"
        catalog = page.locator(".catalog-scroll")
        for number in (31, 61):
            await catalog.evaluate("element => { element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')); }")
            await expect(page.get_by_text(f"보조 카메라 {number}")).to_be_visible()
        assert await page.locator(".catalog-card").count() <= 60
        logical_rows = await page.evaluate(
            """() => {
              const spacers = [...document.querySelectorAll(
                ".catalog-grid > .virtual-spacer"
              )];
              const hidden = spacers.reduce(
                (total, node) => total + parseFloat(node.style.height || "0") / 176,
                0
              );
              return hidden + document.querySelectorAll(".catalog-card").length;
            }"""
        )
        assert logical_rows >= 90
        await catalog.evaluate(
            "element => { element.scrollTop = 0; "
            "element.dispatchEvent(new Event('scroll')); }"
        )
        await expect(page.get_by_text("실외형 네트워크 카메라").first).to_be_visible()
        await page.get_by_role("button", name="실외형 네트워크 카메라").click()
        await expect(page.get_by_text("PTZ 추가 선택품목")).to_be_visible()
        await expect(page.get_by_text("해상도").first).to_be_visible()
        await expect(page.get_by_text("광학줌")).to_be_visible()
        await page.locator(".catalog-card").first.get_by_role("button", name="주품목 추가").click()
        await _wait_for_server_lines(estimates, 1)
        await page.locator(".option-row").get_by_role("button", name="추가").click()
        await _wait_for_server_lines(estimates, 2)
        await page.get_by_role("link", name="관급내역").click()
        await expect(page.locator(".estimate-summary")).to_have_count(1)
        await page.locator(".estimate-summary__open").click()
        await expect(page.locator(".estimate-line")).to_have_count(2)
        for slot in ("A:", "B:", "C:"):
            await expect(page.get_by_text(slot, exact=False).first).to_be_visible()
        await expect(page.get_by_text("해상도").first).to_be_visible()
        await expect(page.get_by_text("광학줌").first).to_be_visible()
        async with page.expect_download() as tsv_download:
            await page.get_by_role("button", name="TSV 내려받기").click()
        tsv = await tsv_download.value
        assert tsv.suggested_filename.endswith(".tsv")
        tsv_content = Path(await tsv.path()).read_text(encoding="utf-8")
        assert "품명\t규격\t업체\t단위\t단가\t수량\t금액" in tsv_content
        assert "실외형 네트워크 카메라\t4K · IP66\t주식회사 화면\t대\t1250000\t1\t1250000" in tsv_content
        await page.route(
            "**/estimates/*/export.xlsx",
            lambda route: route.fulfill(
                status=200,
                body=_workbook_bytes(),
                headers={
                    "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "content-disposition": 'attachment; filename="estimate.xlsx"',
                },
            ),
        )
        async with page.expect_download() as xlsx_download:
            await page.get_by_role("link", name="XLSX 내려받기").click()
        xlsx = await xlsx_download.value
        assert xlsx.suggested_filename.endswith(".xlsx")
        workbook = load_workbook(io.BytesIO(Path(await xlsx.path()).read_bytes()), data_only=True)
        assert workbook["관급내역"]["A2"].value == "실외형 네트워크 카메라"
        assert workbook["관급내역"]["B2"].value == 1
        await page.screenshot(path=EVIDENCE / "catalog-comparison-1440x900.png", full_page=False)
        (EVIDENCE / "catalog-comparison-counters.json").write_text(json.dumps({method: dict(count) for method, count in counters.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_svelte_spa_warm_cache_offline_latest_state_replay(spa_url: str) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    estimates: dict[str, dict[str, object]] = {}
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    offline = {"enabled": False}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context: BrowserContext = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        await _install_contract_routes(page, estimates, counters, offline, total_count=10_000)
        await page.goto(spa_url, wait_until="networkidle")
        await page.get_by_role("button", name="실외형 네트워크 카메라").click()
        await expect(page.get_by_text("PTZ 추가 선택품목")).to_be_visible()
        timing = await page.evaluate(
            """() => new Promise((resolve, reject) => {
              const start = performance.now(); const open = indexedDB.open('g2b-spa', 1);
              open.onerror = () => reject(open.error);
              open.onsuccess = () => {
                const tx = open.result.transaction('catalog_cache', 'readonly');
                const get = tx.objectStore('catalog_cache').get('catalog::price_asc:1');
                get.onerror = () => reject(get.error);
                get.onsuccess = () => resolve({milliseconds: performance.now() - start, found: Boolean(get.result?.value)});
              };
            })"""
        )
        assert timing["found"] is True
        assert timing["milliseconds"] < 100
        assert await page.locator(".catalog-card").count() <= 60
        assert await page.locator(".catalog-card").count() < 10_000
        await page.locator(".catalog-card").first.get_by_role("button", name="주품목 추가").click()
        await _wait_for_server_lines(estimates, 1)
        await page.get_by_role("link", name="관급내역").click()
        await expect(page.locator(".estimate-summary")).to_have_count(1)
        await page.locator(".estimate-summary__open").click()
        estimate_id = (await page.locator(".route-id").text_content()).split(": ", 1)[1]
        for _ in range(100):
            if all(not record["pendingSync"] for record in await _read_estimates(page)):
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("initial estimate sync did not settle")
        await _activate_service_worker(page)
        offline["enabled"] = True
        await context.set_offline(True)
        quantity = page.locator(".estimate-line input[type=number]")
        await quantity.fill("7")
        for _ in range(100):
            pending = await _read_estimates(page)
            if pending and pending[0]["pendingSync"] and pending[0]["document"]["lines"][0]["quantity"] == "7":
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("offline quantity edit was not persisted")
        await page.get_by_role("link", name="검색", exact=True).click()
        await expect(page.locator(".catalog-card").first).to_be_visible()
        await expect(page.locator(".offline-banner")).to_be_visible()
        await page.get_by_role("link", name="관급내역").click()
        await page.locator(".estimate-summary__open").click()
        records = await _read_estimates(page)
        assert records[0]["pendingSync"] is True
        assert records[0]["document"]["lines"][0]["quantity"] == "7"
        await page.get_by_role("button", name="삭제").first.click()
        for _ in range(100):
            tombstone = await _read_estimates(page)
            if tombstone and tombstone[0]["deleted"] and tombstone[0]["pendingSync"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("offline deletion tombstone was not persisted")
        await page.reload(wait_until="domcontentloaded")
        await expect(page.locator(".offline-banner")).to_be_visible()
        records = await _read_estimates(page)
        assert len(records) == 1 and records[0]["deleted"] is True and records[0]["pendingSync"] is True
        await page.screenshot(path=EVIDENCE / "warm-cache-offline-pending.png", full_page=False)
        for _ in range(100):
            failed = await _read_estimates(page)
            if failed and failed[0]["error"]:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("failed replay did not retain an actionable error")
        counters["PUT"].clear()
        counters["DELETE"].clear()
        offline["enabled"] = False
        await context.set_offline(False)
        await page.get_by_role("link", name="관급내역").click()
        await page.get_by_role("button", name="재시도").click()
        await expect(page.locator(".estimate-summary")).to_have_count(0)
        for _ in range(100):
            if counters["DELETE"][f"/api/estimates/{estimate_id}"] == 1:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("latest deletion was not replayed")
        assert counters["PUT"][f"/api/estimates/{estimate_id}"] <= 1
        assert counters["DELETE"][f"/api/estimates/{estimate_id}"] <= 1
        assert counters["DELETE"][f"/api/estimates/{estimate_id}"] == 1
        (EVIDENCE / "warm-cache-offline-timing-counters.json").write_text(json.dumps({"warmIndexedDbGetMilliseconds": timing["milliseconds"], "counters": {method: dict(count) for method, count in counters.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")
        await context.close()
        await browser.close()
