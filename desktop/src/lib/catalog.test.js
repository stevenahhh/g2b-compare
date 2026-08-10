import { describe, expect, it } from "vitest";

import { mergePage, productTitle, relationIdentity, virtualWindow } from "./catalog";

const product = (id) => ({
  product_id: id,
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
  detail_url: `https://example.test/${id}`,
  g2b_url: `https://example.test/${id}`,
  attributes: [{ name: "용도", value: "방범용" }],
});

describe("catalog state helpers", () => {
  it("appends pages without duplicating product IDs", () => {
    const first = { items: [product("P1"), product("P2")], page: 1, page_count: 2, total_count: 3 };
    const second = { items: [product("P2"), product("P3")], page: 2, page_count: 2, total_count: 3 };

    expect(mergePage(first, second, 2, (item) => item.product_id).items.map((item) => item.product_id))
      .toEqual(["P1", "P2", "P3"]);
  });

  it("produces a bounded virtual window at a deterministic offset", () => {
    const items = Array.from({ length: 100 }, (_, index) => product(`P${index}`));
    const window = virtualWindow(items, 1_000, 100, 500, 2);

    expect(window.items.map((item) => item.product_id)).toEqual(
      Array.from({ length: 9 }, (_, index) => `P${index + 8}`),
    );
    expect(window.top).toBe(800);
    expect(window.bottom).toBe(8_300);
  });

  it("keeps the legacy compact title and stable relation fallback identity", () => {
    expect(productTitle(product("P1"))).toBe("영상감시장치, KN-100, 4K, 방범용");
    expect(relationIdentity({
      product_id: "O1",
      parent_product_id: "P1",
      category: "selection",
    })).toBe("P1:selection:O1");
  });
});
