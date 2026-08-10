import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import EstimateRoute from "./EstimateRoute.svelte";

const product = {
  product_id: "P1",
  name: "네트워크 카메라",
  spec: "4K, IP66",
  company_name: "주식회사 코리아넷",
  unit: "대",
  price_won: 1_000,
  contract_method: "MAS",
  delivery_condition: "현장도착도",
  delivery_days: "10",
  contract_end_date: "2027-12-31",
  image_url: "",
  detail_url: "https://example.test/P1",
  g2b_url: "https://example.test/P1",
};
const option = {
  ...product,
  product_id: "O1",
  name: "카메라 브래킷",
  parent_product_id: "P1",
  parent_name: "네트워크 카메라",
  relation_id: "R1",
  relation_kind: "component",
  category: "selection",
};
const line = {
  id: "line-1",
  line_no: 1,
  line_kind: "main",
  product_id: "P1",
  parent_product_id: null,
  relation_id: null,
  offer_operation: null,
  offer_key: null,
  item_name_snapshot: "네트워크 카메라",
  spec_snapshot: "4K, IP66",
  company_snapshot: "주식회사 코리아넷",
  unit_snapshot: "대",
  unit_price_won_snapshot: 1_000,
  quantity: "2",
  comparisons: [
    { estimate_line_id: "line-1", slot: "A", product_id: "A1", relation_id: null, company_snapshot: "적용회사", spec_snapshot: "4K", price_won_snapshot: 900 },
    { estimate_line_id: "line-1", slot: "B", product_id: "B1", relation_id: null, company_snapshot: "비교회사 B", spec_snapshot: "2K", price_won_snapshot: 800 },
    { estimate_line_id: "line-1", slot: "C", product_id: "C1", relation_id: null, company_snapshot: "비교회사 C", spec_snapshot: "HD", price_won_snapshot: 700 },
  ],
};
const document = {
  id: "e".repeat(32),
  title: "비교 문서",
  template_sha256: "template",
  revision: 4,
  created_at: "2026-08-04 09:00:00",
  updated_at: "2026-08-04 09:00:00",
  lines: [line],
};

function savedDocument(request) {
  return {
    ...structuredClone(document),
    title: request.title,
    revision: request.expected_revision + 1,
    lines: request.lines.map((item, index) => ({
      ...item,
      line_no: index + 1,
      comparisons: request.comparisons.filter((comparison) => comparison.estimate_line_id === item.id),
    })),
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function client(overrides = {}) {
  return {
    searchProducts: vi.fn().mockResolvedValue({ items: [product], page: 1, page_count: 1, total_count: 1 }),
    searchRelations: vi.fn().mockImplementation(async ({ category }) => ({
      items: category === "selection" ? [option] : [], page: 1, page_count: 1, total_count: category === "selection" ? 1 : 0,
    })),
    addItem: vi.fn(),
    openProduct: vi.fn(),
    loadView: vi.fn(),
    saveView: vi.fn(),
    listEstimates: vi.fn(),
    createEstimate: vi.fn(),
    readEstimate: vi.fn().mockResolvedValue(structuredClone(document)),
    updateEstimate: vi.fn().mockImplementation(async (_id, request) => savedDocument(request)),
    deleteEstimate: vi.fn().mockResolvedValue(undefined),
    loadEstimateView: vi.fn(),
    saveEstimateView: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

async function renameDocument(nextTitle) {
  await fireEvent.click(screen.getByRole("button", { name: /문서 제목 편집/ }));
  const title = screen.getByRole("textbox", { name: "문서 제목" });
  await fireEvent.input(title, { target: { value: nextTitle } });
  await fireEvent.blur(title);
  await tick();
}

afterEach(() => cleanup());

describe("estimate editor route", () => {
  it("refreshes persisted A/B/C comparisons and provides legacy G2B links and spec tooltips", async () => {
    const refreshed = structuredClone(document);
    refreshed.revision = 5;
    refreshed.lines[0].comparisons = refreshed.lines[0].comparisons.map((comparison) => ({
      ...comparison,
      company_snapshot: comparison.slot === "B" ? "새 비교회사 B" : comparison.company_snapshot,
      g2b_url: `https://shop.g2b.go.kr/link/GMSF001_01/?productId=${comparison.product_id}`,
    }));
    const adapter = client({
      refreshEstimateComparisons: vi.fn().mockResolvedValue(refreshed),
    });
    render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    await fireEvent.click(screen.getByRole("button", { name: "비교군 새로고침" }));
    await settle();

    expect(adapter.refreshEstimateComparisons).toHaveBeenCalledWith(document.id, {
      expected_revision: 4,
    });
    expect(screen.getByText("새 비교회사 B")).toBeInTheDocument();
    expect(screen.getByRole("link", {
      name: "A사 물품식별번호 A1 나라장터에서 보기",
    })).toHaveAttribute(
      "href",
      "https://shop.g2b.go.kr/link/GMSF001_01/?productId=A1",
    );
    const specification = screen.getByRole("button", {
      name: "4K. 전체 규격: 4K",
    });
    await fireEvent.pointerEnter(specification);
    expect(screen.getByRole("tooltip")).toHaveTextContent("전체 규격4K");
    await fireEvent.keyDown(specification, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새로고침 완료" })).toBeInTheDocument();
  });

  it("renders the exact legacy 18-column table without quantity UI and sums applied prices", async () => {
    const adapter = client();
    const view = render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    const table = screen.getByRole("table", { name: "문서 품목별 A사, B사, C사 단가 비교표" });
    const headingRows = table.querySelectorAll("thead tr");
    expect(table.querySelectorAll("colgroup col")).toHaveLength(18);
    expect([...headingRows[0].querySelectorAll("th")].map((cell) => cell.textContent?.trim())).toEqual([
      "연번", "품명", "규격", "단위", "적용단가", "적용회사(A사)", "B사", "C사", "비고",
    ]);
    expect([...headingRows[1].querySelectorAll("th")].map((cell) => cell.textContent?.trim())).toEqual([
      "적용회사", "규격", "물품식별번호", "단가",
      "회사명", "규격", "물품식별번호", "단가",
      "회사명", "규격", "물품식별번호", "단가",
    ]);
    expect(headingRows[0].querySelector("th:first-child")).toHaveAttribute("rowspan", "2");
    expect(headingRows[0].querySelector("th:nth-child(6)")).toHaveAttribute("colspan", "4");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(table.querySelectorAll("tbody td.document-baseline")).toHaveLength(4);
    expect(view.container.querySelector(".document-scroll-link")).toHaveAttribute("href", "#document-table-end");
    expect(screen.getAllByText("적용회사")).toHaveLength(2);
    expect(screen.getByText("비교회사 B")).toBeInTheDocument();
    expect(screen.getByText("비교회사 C")).toBeInTheDocument();
    expect(screen.getByText("문서 합계").parentElement).toHaveTextContent("문서 합계900원");
    expect(screen.queryByText(/수량/)).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();

    await renameDocument("수정된 비교 문서");
    await settle();

    expect(adapter.updateEstimate).toHaveBeenCalledWith(document.id, expect.objectContaining({
      expected_revision: 4,
      title: "수정된 비교 문서",
      lines: [expect.objectContaining({ id: "line-1", quantity: "2" })],
      comparisons: expect.arrayContaining([expect.objectContaining({ slot: "A", product_id: "A1" })]),
    }));
    expect(screen.getByText("저장됨 · 리비전 5")).toBeInTheDocument();
  });

  it("keeps local title edits on a revision conflict and reloads only on explicit action", async () => {
    const latest = { ...structuredClone(document), revision: 5, title: "다른 창의 문서" };
    const adapter = client({
      readEstimate: vi.fn().mockResolvedValueOnce(structuredClone(document)).mockResolvedValueOnce(latest),
      updateEstimate: vi.fn().mockRejectedValue({ code: "revision_conflict" }),
    });
    render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    await renameDocument("현재 편집 문서");
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("현재 편집본은 유지");
    expect(screen.getByRole("button", { name: "문서 제목 편집: 현재 편집 문서" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "최신본 불러오기" }));
    await settle();
    expect(screen.getByRole("button", { name: "문서 제목 편집: 다른 창의 문서" })).toBeInTheDocument();
    expect(screen.getByText("저장됨 · 리비전 5")).toBeInTheDocument();
  });

  it("renders the legacy empty row and adds a selected option without quantity controls", async () => {
    const empty = { ...structuredClone(document), lines: [] };
    const relationsLoaded = deferred();
    const adapter = client({
      readEstimate: vi.fn().mockResolvedValue(empty),
      searchRelations: vi.fn().mockImplementation(async ({ category }) => {
        if (category === "construction") relationsLoaded.resolve();
        return {
          items: category === "selection" ? [option] : [],
          page: 1,
          page_count: 1,
          total_count: category === "selection" ? 1 : 0,
        };
      }),
    });
    render(EstimateRoute, {
      props: { id: document.id, client: adapter, onNavigate: vi.fn(), createId: () => "line-option" },
    });
    await settle();

    const table = screen.getByRole("table", { name: "문서 품목별 A사, B사, C사 단가 비교표" });
    expect(table.querySelector(".document-empty-row td")).toHaveAttribute("colspan", "18");
    await fireEvent.click(screen.getByRole("button", { name: "내역 추가" }));
    await settle();
    const optionAdded = screen.findByRole("button", { name: "옵션 추가" });
    await fireEvent.click(screen.getByRole("button", { name: /네트워크 카메라4K, IP66/ }));
    await relationsLoaded.promise;
    const optionButton = await optionAdded;

    expect(adapter.searchRelations).toHaveBeenCalledTimes(3);
    await fireEvent.click(optionButton);
    await tick();
    expect(table.querySelector(".document-empty-row")).not.toBeInTheDocument();
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(screen.getAllByText("카메라 브래킷")).toHaveLength(2);
    expect(screen.queryByText(/수량/)).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(adapter.updateEstimate).toHaveBeenCalledWith(document.id, expect.objectContaining({
      expected_revision: 4,
      lines: [expect.objectContaining({ id: "line-option", relation_id: "R1" })],
    }));
  });

  it("autosaves title edits in revision order without overwriting a newer local edit", async () => {
    const firstSave = deferred();
    const requests = [];
    const adapter = client({
      updateEstimate: vi.fn((_id, request) => {
        requests.push(request);
        return requests.length === 1 ? firstSave.promise : Promise.resolve(savedDocument(request));
      }),
    });
    render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    await renameDocument("첫 번째 제목");
    await tick();
    expect(adapter.updateEstimate).toHaveBeenCalledTimes(1);
    expect(requests[0]).toMatchObject({ expected_revision: 4, title: "첫 번째 제목" });

    await renameDocument("두 번째 제목");
    await tick();
    expect(adapter.updateEstimate).toHaveBeenCalledTimes(1);

    firstSave.resolve(savedDocument(requests[0]));
    await firstSave.promise;
    await settle();

    expect(adapter.updateEstimate).toHaveBeenCalledTimes(2);
    expect(requests[1]).toMatchObject({ expected_revision: 5, title: "두 번째 제목" });
    expect(screen.getByRole("button", { name: "문서 제목 편집: 두 번째 제목" })).toBeInTheDocument();
    expect(screen.getByText("저장됨 · 리비전 6")).toBeInTheDocument();
  });

  it("keeps failed autosaves dirty until the visible Save retry succeeds", async () => {
    const failedSave = deferred();
    const adapter = client({ updateEstimate: vi.fn().mockReturnValue(failedSave.promise) });
    render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    await renameDocument("복구할 제목");
    await tick();
    expect(adapter.updateEstimate).toHaveBeenCalledTimes(1);

    failedSave.reject(new Error("저장 연결 실패"));
    await expect(failedSave.promise).rejects.toThrow("저장 연결 실패");
    await settle();

    expect(screen.getByText("저장 실패 · 다시 시도")).toBeInTheDocument();
    expect(screen.getByText("저장 연결 실패")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문서 제목 편집: 복구할 제목" })).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "저장" });
    expect(retry).toBeEnabled();

    adapter.updateEstimate.mockImplementation(async (_id, request) => savedDocument(request));
    await fireEvent.click(retry);
    await settle();

    expect(adapter.updateEstimate).toHaveBeenCalledTimes(2);
    expect(screen.getByText("저장됨 · 리비전 5")).toBeInTheDocument();
  });

  it("autosaves row removals immediately", async () => {
    const removalSave = deferred();
    const adapter = client({ updateEstimate: vi.fn().mockReturnValue(removalSave.promise) });
    render(EstimateRoute, { props: { id: document.id, client: adapter, onNavigate: vi.fn() } });
    await settle();

    await fireEvent.click(screen.getByRole("button", { name: "네트워크 카메라 행 삭제" }));
    await tick();
    expect(adapter.updateEstimate).toHaveBeenCalledWith(document.id, expect.objectContaining({
      expected_revision: 4,
      lines: [],
    }));

    const [, removalRequest] = adapter.updateEstimate.mock.calls[0];
    removalSave.resolve(savedDocument(removalRequest));
    await removalSave.promise;
    await settle();

    expect(screen.getByRole("table").querySelector(".document-empty-row")).toBeInTheDocument();
    expect(screen.getByText("저장됨 · 리비전 5")).toBeInTheDocument();
  });

  it("keeps the legacy add search mounted as a non-modal input overlay", async () => {
    const adapter = client();
    const view = render(EstimateRoute, {
      props: { id: document.id, client: adapter, onNavigate: vi.fn() },
    });
    await settle();

    const opener = screen.getByRole("button", { name: "내역 추가" });
    await fireEvent.click(opener);
    await settle();

    const search = screen.getByRole("searchbox", { name: "검색어" });
    const dialog = screen.getByRole("dialog", { name: "물품 검색 결과" });
    expect(dialog).toHaveAttribute("aria-modal", "false");
    expect(view.container.querySelector(".estimate-picker-backdrop")).not.toBeInTheDocument();
    expect(search).toHaveFocus();

    const back = screen.getByRole("button", { name: "닫기" });
    back.focus();
    expect(back).toHaveFocus();

    search.focus();
    await fireEvent.keyDown(search, { key: "Escape" });
    await tick();
    expect(screen.queryByRole("dialog", { name: "물품 검색 결과" })).not.toBeInTheDocument();
    expect(search).toHaveFocus();

    await fireEvent.click(opener);
    await settle();
    back.focus();
    await fireEvent.pointerDown(back);
    await tick();
    expect(screen.queryByRole("dialog", { name: "물품 검색 결과" })).not.toBeInTheDocument();
    expect(back).toHaveFocus();
  });
});
