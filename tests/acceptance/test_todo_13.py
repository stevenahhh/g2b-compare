import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
from pydantic import TypeAdapter

from g2b_compare.services.search_models import CategoryRef
from g2b_compare.web.links import SHOP_HOME
from tests.web.todo13_support import (
    FATAL_RELEASE,
    NO_READY_RELEASE,
    FixtureReader,
    curated_product,
    get,
    named_product,
    observed_product,
    product,
    reader,
    state,
    status_tokens,
)

pytestmark = pytest.mark.asyncio
CSS = Path("src/g2b_compare/web/static/app.css")
CSS_TEXT = CSS.read_text(encoding="utf-8")
NETWORK_ATTEMPT = "render attempted network access"


async def test_happy() -> None:
    response = await get(reader(51))
    assert response.status_code == 200
    assert response.text.count("<tr data-statuses=") == 50
    assert response.text.count('<ol class="comparators">') == 50
    assert response.text.count("<li>") >= 150
    next_page = await get(reader(51), "/?product_name=CCTV&page=2")
    assert next_page.text.count("<tr data-statuses=") == 1
    assert "배송내역" not in next_page.text


async def test_failure_ambiguous_category() -> None:
    fixture = FixtureReader(
        (product(1), product(2, category=("20", "2001"))),
        (CategoryRef("10", "1001"), CategoryRef("20", "2001")),
    )
    response = await get(fixture)
    assert response.status_code == 200
    assert "분류를 선택하세요" in response.text
    assert "10/1001" in response.text
    assert "20/2001" in response.text


async def test_failure_ambiguous_unit() -> None:
    fixture = FixtureReader((product(1, unit="개"), product(2, unit="식")))
    response = await get(fixture, "/?product_name=CCTV&target_price_won=100000")
    assert state(response) == "validation-error"


async def test_failure_xss() -> None:
    payload = "<script>window.pwned=1</script>"
    fixture = FixtureReader((named_product(1, payload),))
    response = await get(fixture)
    assert payload not in response.text
    assert "&lt;script&gt;window.pwned=1&lt;/script&gt;" in response.text


async def test_failure_state_truth_table() -> None:
    cases = (
        (reader(4), "current-results"),
        (reader(0), "no-matches"),
        (reader(4, statuses=("stale",)), "stale"),
        (
            reader(4, statuses=("stale", "sync-failed-last-good")),
            "sync-failed-last-good",
        ),
    )
    for fixture, expected in cases:
        assert state(await get(fixture)) == expected


async def test_failure_forbidden_state_pair() -> None:
    response = await get(reader(4, statuses=("stale",)))
    tokens = status_tokens(response)
    assert state(response) == "stale"
    assert "current-results" not in tokens
    assert "no-matches" not in tokens


async def test_failure_basic_validation_over_fatal() -> None:
    fixture = reader(0, pin_error=FATAL_RELEASE)
    response = await get(fixture, "/?product_name=")
    assert state(response) == "validation-error"


async def test_failure_fatal_over_semantic_validation() -> None:
    fixture = reader(0, pin_error=FATAL_RELEASE)
    response = await get(fixture, "/?product_name=CCTV&category_code=missing")
    assert state(response) == "fatal-error"


async def test_failure_no_active_over_semantic_validation() -> None:
    fixture = reader(0, pin_error=NO_READY_RELEASE)
    response = await get(fixture, "/?product_name=CCTV&category_code=missing")
    assert state(response) == "no-active-snapshot"


async def test_failure_semantic_validation_over_sync_failed() -> None:
    fixture = reader(4, statuses=("sync-failed-last-good",))
    response = await get(fixture, "/?product_name=CCTV&category_code=missing")
    assert state(response) == "validation-error"


async def test_failure_fatal_over_no_active() -> None:
    fatal = await get(reader(0, pin_error=FATAL_RELEASE))
    inactive = await get(reader(0, pin_error=NO_READY_RELEASE))
    assert fatal.status_code == 500
    assert inactive.status_code == 503


async def test_failure_no_active_over_sync_failed() -> None:
    fixture = reader(
        0,
        pin_error=NO_READY_RELEASE,
        statuses=("sync-failed-last-good",),
    )
    assert state(await get(fixture)) == "no-active-snapshot"


async def test_failure_sync_failed_over_stale() -> None:
    fixture = reader(4, statuses=("stale", "sync-failed-last-good"))
    assert state(await get(fixture)) == "sync-failed-last-good"


async def test_failure_stale_over_no_matches() -> None:
    fixture = reader(0, statuses=("stale",))
    assert state(await get(fixture)) == "stale"


async def test_failure_sync_failed_last_good() -> None:
    response = await get(reader(4, statuses=("sync-failed-last-good",)))
    assert "최근 동기화에 실패하여 이전 데이터를 표시합니다" in response.text
    assert response.text.count("<tr data-statuses=") == 4


async def test_failure_stale() -> None:
    response = await get(reader(4, stale_service=True))
    assert state(response) == "stale"
    assert response.status_code == 200


async def test_failure_no_active_snapshot() -> None:
    response = await get(reader(0, pin_error=NO_READY_RELEASE))
    assert response.status_code == 503
    assert state(response) == "no-active-snapshot"


async def test_failure_no_matches() -> None:
    response = await get(reader(0))
    assert state(response) == "no-matches"
    assert "정확히 일치하는 물품이 없습니다" in response.text


async def test_failure_partial_attribute() -> None:
    products = (product(1, coverage="1/3"), *tuple(product(i) for i in range(2, 5)))
    response = await get(FixtureReader(products))
    assert "partial-attribute" in response.text


async def test_failure_insufficient_comparator() -> None:
    response = await get(reader(1))
    assert "insufficient-comparator" in response.text
    assert response.text.count("비교 후보 부족") == 3


async def test_failure_no_evidence() -> None:
    products = tuple(product(index, option="", unit=None) for index in range(4))
    response = await get(FixtureReader(products))
    assert "no-evidence" in response.text
    assert "비교 근거 부족" in response.text


async def test_failure_incompatible_price() -> None:
    products = (product(1, unit=None), *tuple(product(i) for i in range(2, 5)))
    response = await get(
        FixtureReader(products),
        "/?product_name=CCTV&target_price_won=100000&price_unit=개",
    )
    assert "incompatible-price" in response.text
    assert "가격 단위 비교 불가" in response.text


async def test_failure_validation_error_json_422() -> None:
    response = await get(reader(0), "/?product_name=", enhanced=True)
    assert response.status_code == 422
    assert response.json()["primary_state"] == "validation-error"


async def test_failure_validation_error_nojs_200() -> None:
    response = await get(reader(0), "/?product_name=")
    assert response.status_code == 200
    assert state(response) == "validation-error"
    assert 'aria-invalid="true"' in response.text
    assert 'id="product-name-error"' in response.text
    assert "검색 조건을 확인하세요" in response.text


async def test_failure_fatal_error() -> None:
    response = await get(reader(0, pin_error=FATAL_RELEASE))
    assert response.status_code == 500
    assert "검색을 처리할 수 없습니다" in response.text


async def test_failure_exact_token_set() -> None:
    response = await get(reader(1))
    allowed = {"insufficient-comparator"}
    assert status_tokens(response) == allowed
    assert state(response) == "current-results"


async def test_failure_option_event_provenance() -> None:
    observed = await get(FixtureReader((observed_product(1),)))
    curated = await get(FixtureReader((curated_product(1),)))
    assert (
        "배송내역에서 추가선택 역할 관측됨 — 본품 관계 미확정"
        in observed.text
    )
    assert "사용자 내역서에 관계 명시됨" in curated.text


async def test_failure_invalid_stable_link_key(tmp_path: Path) -> None:
    manifest = tmp_path / "todo2.json"
    _write_link_manifest(manifest, "../bad")
    response = await get(reader(1), link_manifest=manifest)
    assert 'href="https://shop.g2b.go.kr/"' in response.text
    assert 'data-copy-id="P000"' in response.text
    assert "../bad" not in response.text


async def test_failure_share_link_redirect(tmp_path: Path) -> None:
    manifest = tmp_path / "todo2.json"
    _write_link_manifest(manifest, "ABC", no_redirect=False)
    response = await get(reader(1), link_manifest=manifest)
    assert 'href="https://shop.g2b.go.kr/"' in response.text
    assert "ctrtItemMngNo=ABC" not in response.text


async def test_failure_transient_link_key(tmp_path: Path) -> None:
    manifest = tmp_path / "todo2.json"
    _write_link_manifest(manifest, "SAFE", extra={"key": "TRANSIENT"})
    response = await get(reader(1), link_manifest=manifest)
    assert "TRANSIENT" not in response.text
    assert "ctrtItemMngNo=SAFE" not in response.text


async def test_failure_missing_deep_link() -> None:
    response = await get(reader(1))
    assert f'href="{SHOP_HOME}"' in response.text
    assert 'data-copy-id="P000"' in response.text


async def test_failure_network_on_render(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(NETWORK_ATTEMPT)

    monkeypatch.setattr("socket.socket.connect", blocked)
    assert (await get(reader(4))).status_code == 200


async def test_failure_js_disabled() -> None:
    response = await get(reader(4), "/?product_name=CCTV&page=1")
    assert response.status_code == 200
    assert response.text.count("<tr data-statuses=") == 4
    assert 'method="get"' in response.text


async def test_failure_bold_element() -> None:
    response = await get(reader(1))
    assert "<b>" not in response.text
    assert "<strong>" not in response.text


async def test_failure_computed_bold_leak() -> None:
    response = await get(reader(4))
    weights = await _browser_weights(response.text, 1440, 900)
    assert set(weights["visible"]) == {"400"}


async def test_failure_pseudo_bold_leak() -> None:
    response = await get(reader(4))
    weights = await _browser_weights(response.text, 1024, 768)
    assert set(weights["pseudo"]) <= {"400"}


async def test_failure_form_control_bold_leak() -> None:
    response = await get(reader(4))
    weights = await _browser_weights(response.text, 375, 812)
    assert set(weights["controls"]) == {"400"}


def _write_link_manifest(
    path: Path,
    stable_key: str,
    *,
    no_redirect: bool = True,
    extra: dict[str, str] | None = None,
) -> None:
    evidence = {
        "stable_contract_item_management_number": stable_key,
        "share_link_preflight": {
            "no_redirect": no_redirect,
            "final_host": "shop.g2b.go.kr",
            "status": 200,
        },
        **(extra or {}),
    }
    _ = path.write_text(
        json.dumps({"product_links": {"P000": evidence}}),
        encoding="utf-8",
    )


async def _browser_weights(
    html: str,
    width: int,
    height: int,
) -> dict[str, list[str]]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.set_content(html)
        _ = await page.add_style_tag(content=CSS_TEXT)
        parts = (
            "() => {",
            'const nodes=[...document.querySelectorAll("body *")];',
            "const visible=nodes.filter((node)=>{",
            "const style=getComputedStyle(node);",
            "const box=node.getBoundingClientRect();",
            'return style.visibility!=="hidden"&&style.display!=="none"',
            "&&box.width>0&&box.height>0;});",
            "const controls=visible.filter((node)=>",
            'node.matches("input,textarea,button,select"));',
            "const pseudo=visible.flatMap((node)=>",
            '["::before","::after"].flatMap((kind)=>{',
            "const style=getComputedStyle(node,kind);",
            'return style.content==="none"?[]:[style.fontWeight];}));',
            "return {",
            "visible:visible.map((node)=>getComputedStyle(node).fontWeight),",
            "controls:controls.map((node)=>getComputedStyle(node).fontWeight),",
            "pseudo};}",
        )
        expression = "".join(parts)
        weights = TypeAdapter(dict[str, list[str]]).validate_python(
            await page.evaluate(expression)
        )
        await browser.close()
    return weights
