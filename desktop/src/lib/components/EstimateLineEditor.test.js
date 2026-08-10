import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import EstimateComparisonTable from "./EstimateComparisonTable.svelte";

const fullSpecification =
  "[별도구매] [22067194] UTP케이블, CAT.5E/CM 4P : 2,740";

const selectedLine = {
  id: "selected-line",
  line_no: 1,
  line_kind: "option",
  product_id: "O1",
  parent_product_id: "P1",
  relation_id: "R1",
  offer_operation: null,
  offer_key: null,
  item_name_snapshot: "추가선택품목",
  spec_snapshot: fullSpecification,
  company_snapshot: "주식회사 코리아넷",
  unit_snapshot: "개",
  unit_price_won_snapshot: 2_740,
  quantity: "1",
  attributes: [{ name: "옵션/기타", value: "옥외 배선용, 회색", unit: "" }],
  comparisons: [
    { estimate_line_id: "selected-line", slot: "A", product_id: "A1", relation_id: null, company_snapshot: "주식회사   적용회사", spec_snapshot: "A 규격", price_won_snapshot: 2_700, g2b_url: "https://example.test/A1" },
    { estimate_line_id: "selected-line", slot: "B", product_id: "B1", relation_id: null, company_snapshot: "(주) 비교회사 B", spec_snapshot: "B 규격", price_won_snapshot: 2_600, g2b_url: "https://example.test/B1" },
    { estimate_line_id: "selected-line", slot: "C", product_id: "C1", relation_id: null, company_snapshot: "㈜비교회사 C", spec_snapshot: "C 규격", price_won_snapshot: 2_500, g2b_url: "https://example.test/C1" },
  ],
};

afterEach(() => cleanup());

describe("selected comparison item row", () => {
  it("keeps 18 columns without quantity controls and applies document formatting", () => {
    render(EstimateComparisonTable, {
      props: { lines: [selectedLine], onRemove: vi.fn() },
    });

    const table = screen.getByRole("table", {
      name: "문서 품목별 A사, B사, C사 단가 비교표",
    });
    const cells = table.querySelectorAll("tbody td");

    expect(table.querySelectorAll("colgroup col")).toHaveLength(18);
    expect(cells[1]).toHaveTextContent("UTP케이블");
    expect(cells[3]).toHaveTextContent("M");
    expect(cells[5]).toHaveTextContent("적용회사");
    expect(cells[9]).toHaveTextContent("비교회사 B");
    expect(cells[13]).toHaveTextContent("비교회사 C");
    expect(screen.queryByText(/수량/u)).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("shows the full selected specification and attributes on focus and hover", async () => {
    render(EstimateComparisonTable, {
      props: { lines: [selectedLine], onRemove: vi.fn() },
    });
    const trigger = screen.getByRole("button", {
      name: `CAT.5E/CM 4P. 전체 규격: ${fullSpecification}`,
    });

    await fireEvent.focus(trigger);
    let tooltip = screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(tooltip).toHaveTextContent(fullSpecification);
    expect(tooltip).toHaveTextContent(/옵션\/기타\s+옥외 배선용, 회색/u);

    await fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await fireEvent.pointerEnter(trigger);
    tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(fullSpecification);
    await fireEvent.pointerLeave(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
