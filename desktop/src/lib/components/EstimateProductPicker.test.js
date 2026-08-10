import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import EstimateProductPicker from "./EstimateProductPicker.svelte";

function product(id) {
  return {
    product_id: id,
    name: `상품 ${id}`,
    spec: `규격 ${id}`,
    company_name: "주식회사 코리아넷",
    unit: "대",
    price_won: 1_000,
    contract_method: "MAS",
    delivery_condition: "현장도착도",
    delivery_days: "10",
    contract_end_date: "2027-12-31",
    image_url: "",
    detail_url: `https://example.test/${id}`,
    g2b_url: `https://example.test/${id}`,
  };
}

function relation(category, id) {
  return {
    ...product(id),
    parent_product_id: "P1",
    parent_name: "상품 P1",
    relation_id: `R-${id}`,
    relation_kind: category === "selection" ? "component" : "additional",
    category,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

function client(overrides = {}) {
  return {
    searchProducts: vi.fn().mockResolvedValue({
      items: [product("P1")], page: 1, page_count: 1, total_count: 1,
    }),
    searchRelations: vi.fn().mockResolvedValue({
      items: [], page: 1, page_count: 1, total_count: 0,
    }),
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

afterEach(() => cleanup());

describe("estimate product picker catalog loading", () => {
  it("scopes editor products to the preferred company and loads one bounded page at a time", async () => {
    const adapter = client({
      searchProducts: vi.fn().mockImplementation(({ page }) => Promise.resolve({
        items: Array.from({ length: 30 }, (_, index) => product(`P${page}-${index + 1}`)),
        page,
        page_count: 924,
        total_count: 27_711,
      })),
    });
    const view = render(EstimateProductPicker, {
      props: { client: adapter, onAdd: vi.fn(() => "") },
    });
    await settle();

    expect(adapter.searchProducts).toHaveBeenCalledTimes(1);
    expect(adapter.searchProducts).toHaveBeenCalledWith({
      company_name: "주식회사 코리아넷",
      query: "",
      sort: "price_asc",
      page: 1,
    });
    expect(view.container.querySelectorAll(".estimate-picker__product")).toHaveLength(30);

    await fireEvent.focus(screen.getByRole("searchbox", { name: "검색어" }));
    await fireEvent.click(screen.getByRole("button", { name: "다음 검색 결과" }));
    await settle();

    expect(adapter.searchProducts.mock.calls.map(([request]) => request.page)).toEqual([1, 2]);
    expect(view.container.querySelectorAll(".estimate-picker__product")).toHaveLength(30);
    expect(screen.getByText("상품 P2-1")).toBeInTheDocument();
  });

  it("loads and groups every relation page without duplicates or response-order drift", async () => {
    const selectionSecond = deferred();
    const selectionThird = deferred();
    const additionalSecond = deferred();
    const adapter = client({
      searchRelations: vi.fn().mockImplementation(({ category, page }) => {
        if (category === "selection" && page === 1) return Promise.resolve({
          items: [relation(category, "S1"), relation(category, "S1")],
          page, page_count: 3, total_count: 3,
        });
        if (category === "selection" && page === 2) return selectionSecond.promise;
        if (category === "selection" && page === 3) return selectionThird.promise;
        if (category === "additional" && page === 1) return Promise.resolve({
          items: [relation(category, "A1")], page, page_count: 2, total_count: 2,
        });
        if (category === "additional" && page === 2) return additionalSecond.promise;
        if (category === "construction" && page === 1) return Promise.resolve({
          items: [relation(category, "C1")], page, page_count: 1, total_count: 1,
        });
        throw new Error(`unexpected relation page ${category}:${page}`);
      }),
    });
    const view = render(EstimateProductPicker, {
      props: { client: adapter, onAdd: vi.fn(() => "") },
    });
    await settle();
    await fireEvent.focus(screen.getByRole("searchbox", { name: "검색어" }));
    await fireEvent.click(screen.getByRole("button", { name: /상품 P1규격 P1/ }));
    await settle();

    expect(adapter.searchRelations.mock.calls.map(([request]) => (
      `${request.category}:${request.page}`
    ))).toEqual([
      "selection:1",
      "selection:2",
    ]);
    selectionThird.resolve({
      items: [relation("selection", "S3")], page: 3, page_count: 3, total_count: 3,
    });
    additionalSecond.resolve({
      items: [relation("additional", "A1"), relation("additional", "A2")],
      page: 2, page_count: 2, total_count: 2,
    });
    await settle();
    expect(view.container.querySelectorAll(".estimate-picker__option")).toHaveLength(0);

    const optionsAdded = screen.findAllByRole("button", { name: "옵션 추가" });
    selectionSecond.resolve({
      items: [relation("selection", "S1"), relation("selection", "S2")],
      page: 2, page_count: 3, total_count: 3,
    });
    expect(await optionsAdded).toHaveLength(6);

    expect([...view.container.querySelectorAll(".estimate-picker__option strong")].map(
      (node) => node.textContent,
    )).toEqual(["상품 S1", "상품 S2", "상품 S3", "상품 A1", "상품 A2", "상품 C1"]);
    expect([...view.container.querySelectorAll(".estimate-picker__option-group h3")].map(
      (node) => node.textContent?.replace(/\s+/g, " ").trim(),
    )).toEqual(["선택품목 3건", "추가선택품목 2건", "공사 1건"]);
    expect(adapter.searchRelations.mock.calls.map(([request]) => (
      `${request.category}:${request.page}`
    )).sort()).toEqual([
      "additional:1", "additional:2", "construction:1",
      "selection:1", "selection:2", "selection:3",
    ]);
  });

  it("cancels a stale high-page search without fanning out trailing pages", async () => {
    const older = deferred();
    const adapter = client({
      searchProducts: vi.fn().mockImplementation(({ query, page }) => {
        if (query === "") return older.promise;
        if (query === "new" && page === 1) return Promise.resolve({
          items: [product("NEW")], page: 1, page_count: 1, total_count: 1,
        });
        throw new Error(`unexpected search ${query}:${page}`);
      }),
    });
    render(EstimateProductPicker, {
      props: { client: adapter, onAdd: vi.fn(() => "") },
    });
    await settle();

    const search = screen.getByRole("searchbox", { name: "검색어" });
    await fireEvent.input(search, { target: { value: "new" } });
    await settle();
    expect(screen.getByText("상품 NEW")).toBeInTheDocument();

    older.resolve({ items: [product("OLD")], page: 1, page_count: 924, total_count: 27_711 });
    await older.promise;
    await settle();

    expect(screen.queryByText("상품 OLD")).not.toBeInTheDocument();
    expect(screen.getByText("상품 NEW")).toBeInTheDocument();
    expect(adapter.searchProducts.mock.calls.map(([request]) => request)).toEqual([
      { company_name: "주식회사 코리아넷", query: "", sort: "price_asc", page: 1 },
      { company_name: "주식회사 코리아넷", query: "new", sort: "price_asc", page: 1 },
    ]);
  });
});
