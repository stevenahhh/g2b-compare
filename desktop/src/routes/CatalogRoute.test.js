import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import CatalogRoute from "./CatalogRoute.svelte";

const mainProduct = {
  product_id: "P0000001",
  name: "영상감시장치",
  spec: "기본, KN-100, 4K",
  company_name: "주식회사 코리아넷",
  unit: "대",
  price_won: 1_250_000,
  contract_method: "MAS",
  delivery_condition: "현장도착도",
  delivery_days: "10",
  contract_end_date: "2027-12-31",
  image_url: "",
  detail_url: "https://example.test/P0000001",
  g2b_url: "https://shop.g2b.go.kr/P0000001",
  attributes: [{ name: "용도", value: "방범용" }],
};

const relationNames = {
  selection: "선택 브래킷",
  additional: "추가 저장장치",
  construction: "설치 공사",
};

function relation(category) {
  return {
    ...mainProduct,
    product_id: `O-${category}`,
    name: relationNames[category],
    parent_product_id: mainProduct.product_id,
    relation_kind: category === "selection" ? "component" : "additional",
    category,
    relation_id: `R-${category}`,
  };
}

function client(overrides = {}) {
  return {
    searchProducts: vi.fn().mockResolvedValue({
      items: [mainProduct], page: 1, page_count: 1, total_count: 1,
    }),
    searchRelations: vi.fn().mockImplementation(async ({ category }) => ({
      items: [relation(category)], page: 1, page_count: 1, total_count: 1,
    })),
    addItem: vi.fn().mockResolvedValue({ estimate_id: "E1", line_count: 1 }),
    openProduct: vi.fn().mockResolvedValue(undefined),
    loadView: vi.fn().mockResolvedValue(null),
    saveView: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function settleView() {
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

afterEach(() => cleanup());

describe("catalog route", () => {
  it("renders complete metadata and all four deterministic sorts", async () => {
    const adapter = client();
    render(CatalogRoute, { props: { client: adapter } });
    await settleView();

    expect(screen.getByText("영상감시장치, KN-100, 4K, 방범용")).toBeInTheDocument();
    expect(screen.getByText("1,250,000원 / 대")).toBeInTheDocument();
    expect(screen.getByText(/MAS · 현장도착도 · 납기 10일/)).toBeInTheDocument();
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "낮은 가격순", "높은 가격순", "품명순", "식별번호순",
    ]);
  });

  it("loads three independent relation groups when a product is selected", async () => {
    const adapter = client();
    render(CatalogRoute, { props: { client: adapter } });
    await settleView();

    await fireEvent.click(screen.getByRole("button", { name: /영상감시장치 상품 이미지/ }));
    await settleView();

    expect(adapter.searchRelations).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("tab", { name: /^선택품목1$/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("선택 브래킷")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("tab", { name: /^추가선택품목1$/ }));
    await tick();
    expect(screen.getByText("추가 저장장치")).toBeInTheDocument();
  });

  it("does not offer a relation owned by another product as an addable selected-product option", async () => {
    const foreignRelation = {
      ...relation("selection"),
      product_id: "O-foreign",
      name: "다른 본품 전용 브래킷",
      parent_product_id: "P0000002",
      parent_name: "다른 본품",
      relation_id: "R-foreign",
    };
    const adapter = client({
      searchRelations: vi.fn().mockResolvedValue({
        items: [foreignRelation], page: 1, page_count: 1, total_count: 1,
      }),
    });
    render(CatalogRoute, { props: { client: adapter } });
    await settleView();

    await fireEvent.click(screen.getByRole("button", { name: /영상감시장치 상품 이미지/ }));
    await settleView();

    expect(adapter.searchRelations).toHaveBeenCalledWith(expect.objectContaining({
      parent_product_id: mainProduct.product_id,
    }));
    expect(screen.queryByText(foreignRelation.name)).not.toBeInTheDocument();
    expect(adapter.addItem).not.toHaveBeenCalled();
  });

  it("uses the relation row's parent identity for deterministic option adds", async () => {
    const adapter = client();
    render(CatalogRoute, { props: { client: adapter } });
    await settleView();

    await fireEvent.click(screen.getByRole("button", { name: /영상감시장치 상품 이미지/ }));
    await settleView();
    await fireEvent.click(screen.getByText("선택 브래킷").closest("article").querySelector(".button"));
    await settleView();

    expect(adapter.addItem).toHaveBeenCalledWith({
      product_id: "O-selection",
      line_kind: "option",
      parent_product_id: mainProduct.product_id,
      relation_id: "R-selection",
    });
  });

  it("uses the typed add and external-open actions", async () => {
    const adapter = client();
    render(CatalogRoute, { props: { client: adapter } });
    await settleView();

    await fireEvent.click(screen.getByRole("button", { name: "나라장터에서 보기" }));
    await fireEvent.click(screen.getByRole("button", { name: "리스트에 추가" }));
    await settleView();

    expect(adapter.openProduct).toHaveBeenCalledWith(mainProduct.g2b_url);
    expect(adapter.addItem).toHaveBeenCalledWith({
      product_id: mainProduct.product_id,
      line_kind: "main",
      parent_product_id: null,
      relation_id: null,
    });
    expect(screen.getByText("리스트에 추가함 · 1개 품목")).toBeInTheDocument();
  });
});
