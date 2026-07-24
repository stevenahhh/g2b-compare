from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import httpx
import pytest
from playwright.async_api import async_playwright

from g2b_compare.db.migrate import migrate
from g2b_compare.priority_store import PriorityStore
from g2b_compare.web.app import create_app

ESTIMATE_SCRIPT = Path("src/g2b_compare/web/static/estimate.js").resolve()


def _seed_product(
    database: Path,
    product_id: str = "25454886",
    *,
    price_won: int = 3_281_000,
    company_name: str = "공급사",
    spec: str = "영상감시장치 800만화소",
) -> None:
    PriorityStore(database)
    migrate(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_products "
            "(product_id, operation, contract_number, contract_sequence, "
            "category_number, category_name, detail_category_number, spec, "
            "company_name, unit, price_won, contract_method, delivery_condition, "
            "delivery_days, contract_end_date, image_url, detail_url, raw_json, "
            "observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?)",
            (
                product_id,
                "getMASCntrctPrdctInfoList",
                "0023H000001",
                "1",
                "46171622",
                "영상감시장치",
                "4617162201",
                spec,
                company_name,
                "조",
                price_won,
                "다수공급자계약",
                "현장설치도",
                "60",
                "20271231",
                "",
                "https://shop.g2b.go.kr/detail",
                "{}",
                "2026-07-21T00:00:00+00:00",
            ),
        )


async def _create_draft(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/estimates",
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].removeprefix("/estimates/")


@pytest.mark.asyncio
async def test_estimates_entry_lists_saved_drafts_without_creating_an_empty_one(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/estimates")

    assert response.status_code == 200
    assert "저장된 관급내역이 없음" in response.text
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM estimate_drafts").fetchone()
    assert count == (0,)


@pytest.mark.asyncio
async def test_new_estimate_uses_an_automatic_name(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        response = await client.get(f"/estimates/{estimate_id}")

    assert response.status_code == 200
    assert re.search(r"1-\d{8}-\d{6}", response.text)
    assert "0 / 9" in response.text
    assert "Excel에 붙여넣기" in response.text
    assert ".xlsx 내보내기 · 보조" in response.text


@pytest.mark.asyncio
async def test_only_non_empty_estimates_remain_in_the_saved_list(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        empty_id = await _create_draft(client)
        saved_id = await _create_draft(client)
        _ = await client.post(
            f"/estimates/{saved_id}/lines",
            data={"product_id": "25454886", "quantity": "1"},
            follow_redirects=False,
        )
        saved_list = await client.get("/estimates")

    assert saved_list.status_code == 200
    assert f'href="/estimates/{saved_id}"' in saved_list.text
    assert f'href="/estimates/{empty_id}"' not in saved_list.text
    assert "내역 1건" in saved_list.text
    with sqlite3.connect(database) as connection:
        ids = {
            str(row[0]) for row in connection.execute("SELECT id FROM estimate_drafts")
        }
    assert ids == {saved_id}


@pytest.mark.asyncio
async def test_saved_estimate_can_be_deleted_from_the_list(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        estimate_id = await _create_draft(client)
        _ = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25454886", "quantity": "1"},
            follow_redirects=False,
        )
        deleted = await client.post(
            f"/estimates/{estimate_id}/delete", follow_redirects=False
        )
        saved_list = await client.get("/estimates")

    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/estimates"
    assert f'href="/estimates/{estimate_id}"' not in saved_list.text
    with sqlite3.connect(database) as connection:
        counts = (
            connection.execute("SELECT COUNT(*) FROM estimate_drafts").fetchone(),
            connection.execute("SELECT COUNT(*) FROM estimate_lines").fetchone(),
            connection.execute("SELECT COUNT(*) FROM estimate_comparisons").fetchone(),
        )
    assert counts == ((0,), (0,), (0,))


@pytest.mark.asyncio
async def test_add_main_line_update_quantity_and_delete(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        added = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25454886", "quantity": "1"},
            follow_redirects=False,
        )
        editor = await client.get(f"/estimates/{estimate_id}")
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT id FROM estimate_lines WHERE estimate_id = ?",
                (estimate_id,),
            ).fetchone()
        assert row is not None
        line_id = str(row[0])
        updated = await client.patch(
            f"/estimates/{estimate_id}/lines/{line_id}",
            json={"quantity": "2.5"},
        )
        persisted = await client.get(f"/estimates/{estimate_id}")
        deleted = await client.delete(f"/estimates/{estimate_id}/lines/{line_id}")

    assert added.status_code == 303
    assert "본품 [25454886]" in editor.text
    assert 'data-copy-estimate="' in editor.text
    assert "Excel에 붙여넣기" in editor.text
    assert 'data-copy-value="영상감시장치"' in editor.text
    assert updated.status_code == 200
    assert updated.json()["quantity"] == "2.5"
    assert 'value="2.5"' in persisted.text
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_verified_option_is_added_with_parent_context(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(
        database,
        "25454886",
        price_won=1_000_000,
        company_name="주식회사 코리아넷",
    )
    _seed_product(database, "25454887", price_won=5_500_000, company_name="B사")
    _seed_product(database, "25454888", price_won=6_000_000, company_name="C사")
    app = create_app(database=database, home=tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO verified_product_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "relation-a",
                "getMASCntrctPrdctInfoList",
                "offer-a",
                "25454886",
                "25560063",
                "additional",
                1,
                "주식회사 코리아넷",
                "[25560063] 저장장치 옵션",
                5_431_000,
                "https://shop.g2b.go.kr/detail",
                "2026-07-21T00:00:00+00:00",
                1,
            ),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        added = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={
                "product_id": "25560063",
                "relation_id": "relation-a",
                "quantity": "1.5",
            },
            follow_redirects=False,
        )
        editor = await client.get(f"/estimates/{estimate_id}")

    assert added.status_code == 303
    assert "본품 [25454886] &gt; 옵션 [25560063]" in editor.text
    assert "5,431,000" in editor.text
    assert editor.text.count("data-comparison") == 3


@pytest.mark.asyncio
async def test_selected_product_is_comparison_a_and_attributes_are_visible(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    attributes = json.dumps(
        {
            "pdctAtrbNm": "01$x$x$x$용도$ATTR1|02$x$x$x$구성$ATTR2",
            "pdctAtrbCdDtlNm": "옥외(방범)감시시스템$Bullet카메라:MODEL-A, POE인젝터",
            "snymNm": "Bullet카메라:800만화소/광학18배줌||PoE인젝터:1Port/PoE",
        },
        ensure_ascii=False,
    )
    _seed_product(
        database,
        "25454886",
        price_won=1_000_000,
        company_name="주식회사 코리아넷",
    )
    _seed_product(database, "25454887", price_won=900_000, company_name="저가사")
    _seed_product(database, "25454888", price_won=1_100_000, company_name="고가사")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET raw_json = ? WHERE product_id = ?",
            (attributes, "25454886"),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        estimate_id = await _create_draft(client)
        _ = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25454886", "quantity": "1"},
            follow_redirects=False,
        )
        editor = await client.get(f"/estimates/{estimate_id}")

    with sqlite3.connect(database) as connection:
        slot_a = connection.execute(
            "SELECT product_id FROM estimate_comparisons "
            "WHERE estimate_line_id = (SELECT id FROM estimate_lines LIMIT 1) "
            "AND slot = 'A'"
        ).fetchone()
    assert slot_a == ("25454886",)
    assert "상품 속성 정보" in editor.text
    assert "Bullet카메라:800만화소/광학18배줌" in editor.text


@pytest.mark.asyncio
async def test_verified_option_creates_an_estimate_when_none_is_active(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database, "25454886", price_won=1_000_000)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO verified_product_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "relation-a",
                "getMASCntrctPrdctInfoList",
                "offer-a",
                "25454886",
                "25560063",
                "additional",
                1,
                "공급사",
                "[25560063] 저장장치 옵션",
                5_431_000,
                "https://shop.g2b.go.kr/detail",
                "2026-07-21T00:00:00+00:00",
                1,
            ),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        added = await client.post(
            "/estimates/lines",
            data={
                "product_id": "25560063",
                "relation_id": "relation-a",
                "quantity": "1",
            },
            follow_redirects=False,
        )

    assert added.status_code == 303
    assert re.fullmatch(r"/estimates/[a-f0-9]{32}", added.headers["location"])
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT line_kind, product_id FROM estimate_lines"
        ).fetchone()
    assert row == ("option", "25560063")


@pytest.mark.asyncio
async def test_contract_group_option_creates_an_estimate_with_clicked_parent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database, "25454886", price_won=1_000_000)
    _seed_product(database, "25560063", price_won=50_000)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_product_contract_groups VALUES (?, ?)",
            ("25454886", "contract-group-a"),
        )
        connection.execute(
            "INSERT INTO priority_contract_options VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "contract-group-a",
                "relation-a",
                "25560063",
                "additional",
                1,
                "option-company",
                "[25560063] option",
                50_000,
                "2026-07-22T00:00:00+00:00",
                1,
            ),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        added = await client.post(
            "/estimates/lines",
            data={
                "product_id": "25560063",
                "parent_product_id": "25454886",
                "relation_id": "relation-a",
                "quantity": "1",
            },
            follow_redirects=False,
        )

    assert added.status_code == 303
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT line_kind, product_id, parent_product_id FROM estimate_lines"
        ).fetchone()
    assert row == ("option", "25560063", "25454886")


@pytest.mark.asyncio
async def test_cable_comparisons_keep_the_same_cable_kind(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(
        database,
        "24492324",
        price_won=18_000,
        company_name="주식회사 코리아넷",
        spec="통신케이블어셈블리, JM-LAN1002, 2m, LAN케이블",
    )
    _seed_product(
        database,
        "24492331",
        price_won=19_000,
        company_name="A사",
        spec="통신케이블어셈블리, JM-LAN2002, 2m, LAN케이블",
    )
    _seed_product(
        database,
        "24492332",
        price_won=20_000,
        company_name="B사",
        spec="통신케이블어셈블리, B-LAN3003, 3m, LAN케이블",
    )
    _seed_product(
        database,
        "24492333",
        price_won=21_000,
        company_name="B사",
        spec="통신케이블어셈블리, B-LAN3002, 2m, LAN케이블",
    )
    _seed_product(
        database,
        "24492334",
        price_won=22_000,
        company_name="C사",
        spec="통신케이블어셈블리, C-LAN3002, 2m, LAN케이블",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE priority_products SET category_name = '통신케이블어셈블리', "
            "category_number = '26121600'"
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "24492324", "quantity": "1"},
            follow_redirects=False,
        )

    with sqlite3.connect(database) as connection:
        comparisons = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT company_snapshot, spec_snapshot FROM estimate_comparisons"
            )
        }
    assert {company for company, _spec in comparisons} == {
        "주식회사 코리아넷",
        "A사",
        "B사",
    }
    assert all("2m, LAN케이블" in spec for _company, spec in comparisons)


@pytest.mark.asyncio
async def test_disconnected_option_candidate_cannot_be_added(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    PriorityStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO priority_options VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "공급사", "추가선택품목", "25104211", "저장장치", "8TB", 100, ""),
        )
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        response = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25104211", "quantity": "1"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "검증된 본품/옵션 관계가 필요함"


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-Infinity"])
async def test_add_line_rejects_non_finite_quantity(
    tmp_path: Path,
    quantity: str,
) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(database)
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        response = await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25454886", "quantity": quantity},
            follow_redirects=False,
        )

    assert response.status_code == 422
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM estimate_lines").fetchone() == (
            0,
        )


@pytest.mark.asyncio
async def test_tsv_encoder_neutralizes_formulas_and_delimiters() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.set_content(
            """
            <main data-estimate-id="draft">
              <button data-copy-estimate>copy</button>
              <table><tbody>
                <tr data-line-id="line">
                  <td data-copy-value="1"></td>
                  <td data-copy-value="main"></td>
                  <td data-copy-value="=HYPERLINK('x')"></td>
                  <td data-copy-value="a&#9;b&#10;c"></td>
                  <td data-copy-value="unit"></td>
                  <td><input data-copy-input value="2"></td>
                  <td data-copy-value="100"></td>
                  <td data-copy-value="200"></td>
                  <td data-copy-value="25000001"></td>
                  <td data-copy-value="@company"></td>
                </tr>
                <tr><td>
                  <article data-comparison data-company="+A" data-spec="A&#9;spec"
                    data-product-id="26000001" data-price="100"></article>
                  <article data-comparison data-company="B" data-spec="B spec"
                    data-product-id="26000002" data-price="200"></article>
                  <article data-comparison data-company="C" data-spec="C spec"
                    data-product-id="26000003" data-price="300"></article>
                </td></tr>
              </tbody></table>
            </main>
            """
        )
        await page.evaluate(
            """
            Object.defineProperty(navigator, "clipboard", {
              value: { writeText: text => { globalThis.copiedTsv = text; } },
              configurable: true,
            })
            """
        )
        await page.add_script_tag(path=ESTIMATE_SCRIPT)
        await page.locator("[data-copy-estimate]").click()
        copied = await page.evaluate("globalThis.copiedTsv")
        await browser.close()

    lines = str(copied).splitlines()
    assert len(lines) == 2
    assert len(lines[0].split("\t")) == 22
    cells = lines[1].split("\t")
    assert len(cells) == 22
    assert cells[2] == "'=HYPERLINK('x')"
    assert cells[3] == "a b c"
    assert cells[9] == "'@company"
    assert cells[10] == "'+A"
    assert cells[11] == "A spec"


@pytest.mark.asyncio
async def test_delete_uses_page_modal_instead_of_browser_confirm() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.set_content(
            """
            <main data-estimate-id="draft">
              <table><tbody><tr data-line-id="line" data-unit-price="1">
                <td><button class="delete-line" type="button">삭제</button></td>
              </tr></tbody></table>
            </main>
            <dialog data-confirm-dialog>
              <form method="dialog">
                <h2>내역 삭제</h2>
                <p>선택한 내역을 삭제할까요?</p>
                <button type="submit" value="cancel">취소</button>
                <button type="submit" value="confirm">삭제</button>
              </form>
            </dialog>
            """
        )
        await page.evaluate(
            """
            window.confirm = () => { throw new Error("browser confirm called"); };
            window.deleteRequests = 0;
            window.fetch = async () => {
              window.deleteRequests += 1;
              return { ok: false };
            };
            """
        )
        await page.add_script_tag(path=ESTIMATE_SCRIPT)
        await page.evaluate("window.deleteRequests = 0")
        await page.locator(".delete-line").click()
        modal_open = await page.locator("[data-confirm-dialog]").evaluate(
            "dialog => dialog.open"
        )
        await page.locator('[data-confirm-dialog] button[value="cancel"]').click()
        requests_after_cancel = await page.evaluate("window.deleteRequests")
        await page.locator(".delete-line").click()
        await page.locator('[data-confirm-dialog] button[value="confirm"]').click()
        requests_after_confirm = await page.evaluate("window.deleteRequests")
        await browser.close()

    assert modal_open is True
    assert requests_after_cancel == 0
    assert requests_after_confirm == 1


@pytest.mark.asyncio
async def test_export_route_downloads_fixed_template_workbook(tmp_path: Path) -> None:
    database = tmp_path / "g2b.sqlite3"
    _seed_product(
        database,
        "25454886",
        price_won=1_000_000,
        company_name="주식회사 코리아넷",
    )
    _seed_product(database, "25454887", price_won=1_050_000, company_name="B사")
    _seed_product(database, "25454888", price_won=1_100_000, company_name="C사")
    app = create_app(database=database, home=tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        estimate_id = await _create_draft(client)
        await client.post(
            f"/estimates/{estimate_id}/lines",
            data={"product_id": "25454886", "quantity": "1"},
        )
        editor = await client.get(f"/estimates/{estimate_id}")
        response = await client.get(f"/estimates/{estimate_id}/export.xlsx")

    comparison_ids = re.findall(
        r'<article data-comparison[^>]+data-product-id="(\d+)"', editor.text
    )
    assert comparison_ids == ["25454886", "25454887", "25454888"]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content.startswith(b"PK")
