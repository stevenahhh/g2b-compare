import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import EstimateDocumentActions from "./EstimateDocumentActions.svelte";

const comparisons = ["A", "B", "C"].map((slot, index) => ({
  estimate_line_id: "line-1",
  slot,
  product_id: `${slot}0000001`,
  relation_id: null,
  company_snapshot: `${slot}사`,
  spec_snapshot: `${slot} 규격`,
  price_won_snapshot: 1_000 + index,
}));
const document = {
  id: "estimate-1",
  title: "비교 문서",
  template_sha256: "template",
  revision: 1,
  created_at: "2026-08-04T09:00:00Z",
  updated_at: "2026-08-04T09:00:00Z",
  lines: [{
    id: "line-1", line_no: 1, line_kind: "main", product_id: "P0000001",
    parent_product_id: null, relation_id: null, offer_operation: null, offer_key: null,
    item_name_snapshot: "카메라", spec_snapshot: "4K", company_snapshot: "선택회사",
    unit_snapshot: "대", unit_price_won_snapshot: 1_000, quantity: "1", comparisons,
  }],
};

async function settle() {
  await Promise.resolve();
  await tick();
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("estimate document actions", () => {
  it("copies and exports through the typed client with completion feedback", async () => {
    const client = {
      copyEstimateTable: vi.fn().mockResolvedValue({ row_count: 1 }),
      exportEstimateWorkbook: vi.fn().mockResolvedValue({ path: "C:/exports/estimate.xlsx", file_name: "estimate.xlsx" }),
    };
    render(EstimateDocumentActions, { props: { document, client } });

    await fireEvent.click(screen.getByRole("button", { name: "표 복사" }));
    await settle();
    expect(client.copyEstimateTable).toHaveBeenCalledWith("estimate-1");
    expect(screen.getByText("표 복사됨 · 1행")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "XLSX 내보내기" }));
    await settle();
    expect(client.exportEstimateWorkbook).toHaveBeenCalledWith("estimate-1");
    expect(screen.getByText("XLSX 저장됨 · estimate.xlsx")).toBeInTheDocument();
  });

  it("does not expose workbook export until every row has A, B, and C", () => {
    const incomplete = structuredClone(document);
    incomplete.lines[0].comparisons = comparisons.slice(0, 2);
    render(EstimateDocumentActions, {
      props: {
        document: incomplete,
        client: { copyEstimateTable: vi.fn(), exportEstimateWorkbook: vi.fn() },
      },
    });

    expect(screen.queryByRole("button", { name: "XLSX 내보내기" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "표 복사" })).toBeEnabled();
  });

  it("keeps replacement feedback for a fresh legacy interval without a stale clear", async () => {
    vi.useFakeTimers();
    const client = {
      copyEstimateTable: vi.fn().mockResolvedValue({ row_count: 1 }),
      exportEstimateWorkbook: vi.fn().mockResolvedValue({ path: "C:/exports/replacement.xlsx", file_name: "replacement.xlsx" }),
    };
    render(EstimateDocumentActions, { props: { document, client } });

    await fireEvent.click(screen.getByRole("button", { name: "표 복사" }));
    await settle();
    await vi.advanceTimersByTimeAsync(800);

    await fireEvent.click(screen.getByRole("button", { name: "XLSX 내보내기" }));
    await settle();
    await vi.advanceTimersByTimeAsync(800);
    await tick();

    expect(screen.getByText("XLSX 저장됨 · replacement.xlsx")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(799);
    await tick();
    expect(screen.getByText("XLSX 저장됨 · replacement.xlsx")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(1);
    await tick();
    expect(screen.queryByText("XLSX 저장됨 · replacement.xlsx")).not.toBeInTheDocument();
  });

  it("cancels the pending feedback deadline when unmounted", async () => {
    vi.useFakeTimers();
    const client = {
      copyEstimateTable: vi.fn().mockRejectedValue(new Error("clipboard unavailable")),
      exportEstimateWorkbook: vi.fn(),
    };
    const view = render(EstimateDocumentActions, { props: { document, client } });

    await fireEvent.click(screen.getByRole("button", { name: "표 복사" }));
    await settle();
    expect(screen.getByText("표를 복사하지 못했습니다.")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(1);

    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
