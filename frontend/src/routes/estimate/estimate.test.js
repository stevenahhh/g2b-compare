import { describe, expect, it, vi } from "vitest";

import { loadDocumentProducts } from "./catalog.js";
import { tableTsv } from "./comparison.js";
import { appendDocumentLine } from "./document.js";
import { closeOnEscape, titleKeyAction } from "./keyboard.js";

const product = {
  product_id: "00000001",
  name: "네트워크 카메라",
  spec: "4K, IP66",
  unit: "대",
  price_won: 1250000,
  company_name: "주식회사 코리아넷",
};
const services = (overrides = {}) => ({
  getCatalogCache: vi.fn().mockResolvedValue(undefined),
  putCatalogCache: vi.fn().mockResolvedValue(undefined),
  requestJson: vi.fn().mockResolvedValue({ items: [product], total_count: 1 }),
  ...overrides,
});

describe("document catalog cache boundaries", () => {
  it("treats a rejected cache read as a miss and still fetches products", async () => {
    const dependencies = services({
      getCatalogCache: vi.fn().mockRejectedValue(new Error("IDB closed")),
    });
    const loaded = await loadDocumentProducts(
      "camera",
      "price_asc",
      dependencies,
    );
    expect(loaded.cached).toBeNull();
    expect(loaded.result).toEqual({ items: [product], total_count: 1 });
    expect(dependencies.requestJson).toHaveBeenCalledOnce();
  });
  it("keeps online results usable when a cache write rejects", async () => {
    const dependencies = services({
      putCatalogCache: vi.fn().mockRejectedValue(new Error("quota")),
    });
    await expect(
      loadDocumentProducts("", "price_asc", dependencies),
    ).resolves.toMatchObject({ result: { items: [product] } });
  });
});

describe("document line mutations", () => {
  it("preserves snapshots, blocks a tenth line, and rejects duplicate options", () => {
    const empty = { id: "draft", title: "문서", lines: [] };
    expect(appendDocumentLine(empty, product, () => "line-1")).toMatchObject({
      error: "",
      document: {
        lines: [
          {
            id: "line-1",
            line_kind: "main",
            product_id: "00000001",
            item_name_snapshot: "네트워크 카메라",
            spec_snapshot: "4K, IP66",
            unit_snapshot: "대",
            quantity: "1",
          },
        ],
      },
    });
    const full = {
      ...empty,
      lines: Array.from({ length: 9 }, (_, index) => ({ id: String(index) })),
    };
    expect(appendDocumentLine(full, product, () => "unused")).toEqual({
      document: full,
      error: "문서에는 품목을 최대 9개까지 추가할 수 있음.",
    });
    const option = { ...product, relation_id: "option-1" };
    const duplicate = {
      ...empty,
      lines: [{ id: "old", relation_id: "option-1" }],
    };
    expect(appendDocumentLine(duplicate, option, () => "unused")).toEqual({
      document: duplicate,
      error: "이미 추가된 하위 품목임.",
    });
  });
});

describe("comparison TSV", () => {
  it("keeps clipboard columns while neutralizing formulas", () => {
    const document = {
      lines: [
        {
          ...product,
          id: "line-1",
          line_kind: "main",
          item_name_snapshot: "=SUM(A1)",
          spec_snapshot: "@spec\tvalue",
          unit_snapshot: "대",
          unit_price_won_snapshot: 100,
        },
      ],
    };
    const remote = {
      lines: [
        {
          id: "line-1",
          attributes: [],
          comparisons: [
            {
              slot: "A",
              company_snapshot: "+회사",
              spec_snapshot: "a\nb",
              product_id: "00000001",
              price_won_snapshot: 100,
            },
          ],
        },
      ],
    };
    const clipboard = tableTsv(document, remote)
      .split("\n")
      .map((row) => row.split("\t"));
    expect(clipboard.map((row) => row.length)).toEqual([17, 17]);
    expect(clipboard[1].slice(0, 6)).toEqual([
      "'=SUM(A1)",
      "'@spec value",
      "대",
      "100",
      "'+회사",
      "a b",
    ]);
  });
});

describe("keyboard contracts", () => {
  it("commits titles on Enter and dismisses title, search, and tooltip on Escape", () => {
    expect(titleKeyAction("Enter")).toBe("commit");
    expect(titleKeyAction("Escape")).toBe("cancel");
    expect(closeOnEscape("Escape")).toBe(true);
    expect(closeOnEscape("Enter")).toBe(false);
  });
});
