import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App.svelte";

function client(overrides = {}) {
  return {
    searchProducts: vi.fn().mockResolvedValue({ items: [], page: 1, page_count: 1, total_count: 0 }),
    searchRelations: vi.fn(), addItem: vi.fn(), openProduct: vi.fn(),
    loadView: vi.fn().mockResolvedValue(null), saveView: vi.fn().mockResolvedValue(undefined),
    listEstimates: vi.fn().mockResolvedValue([]), createEstimate: vi.fn(), readEstimate: vi.fn(),
    updateEstimate: vi.fn().mockImplementation(async (id, request) => estimate(
      id,
      request.expected_revision + 1,
      request.title,
    )), deleteEstimate: vi.fn(), loadEstimateView: vi.fn(),
    saveEstimateView: vi.fn().mockResolvedValue(undefined),
    getDataStatus: vi.fn().mockResolvedValue({
      company_count: 0, product_count: 0, relation_count: 0, option_row_count: 0,
      unique_option_count: 0, pending_api_target_count: 0, pending_site_product_count: 0,
      ready: false, readiness: "empty", error: null,
    }),
    runDataSync: vi.fn(), runDataDiagnostics: vi.fn(),
    exportEstimateWorkbook: vi.fn(), copyEstimateTable: vi.fn(),
    loadDesktopView: vi.fn().mockResolvedValue(null), saveDesktopView: vi.fn().mockResolvedValue(undefined),
    getReconciliationStatus: vi.fn().mockResolvedValue({ state: "idle", online: true, queued_count: 0, conflicts: [] }),
    replayPendingChanges: vi.fn(), resolveReconciliationConflict: vi.fn(),
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

function deferred() {
  let resolve;
  const promise = new Promise((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

function estimate(id, revision, title) {
  return {
    id,
    title,
    template_sha256: "template",
    revision,
    created_at: "2026-08-04 09:00:00",
    updated_at: "2026-08-04 09:00:00",
    lines: [],
  };
}

afterEach(() => cleanup());

describe("desktop shell routing", () => {
  it("navigates between the preserved catalog and estimate list from the header", async () => {
    render(App, { props: { client: client(), initialPath: "/estimates" } });
    await settle();
    expect(screen.getByRole("heading", { name: "문서 작성" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문서 작성" })).toHaveAttribute("aria-current", "page");

    await fireEvent.click(screen.getByRole("button", { name: "물품 검색" }));
    await settle();
    expect(screen.getByRole("heading", { name: "물품 검색" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "물품 검색" })).toHaveAttribute("aria-current", "page");

    const brand = screen.getByRole("button", { name: "코리아넷 문서 작성 홈" });
    expect(brand.querySelector("img")).toHaveAttribute("src", expect.stringContaining("KakaoTalk_20260804_113126254"));
    await fireEvent.click(brand);
    await settle();
    expect(screen.getByRole("heading", { name: "문서 작성" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문서 작성" })).toHaveAttribute("aria-current", "page");
  });

  it("reconciles external estimate saves without allowing stale reads to overwrite the latest document", async () => {
    const id = "a".repeat(32);
    const older = deferred();
    const newer = deferred();
    let receiveChange;
    const unlisten = vi.fn();
    const subscribeEstimateChanges = vi.fn(async (listener) => {
      receiveChange = listener;
      return unlisten;
    });
    const adapter = client({
      readEstimate: vi.fn()
        .mockResolvedValueOnce(estimate(id, 4, "초기 문서"))
        .mockReturnValueOnce(older.promise)
        .mockReturnValueOnce(newer.promise),
    });
    const view = render(App, {
      props: { client: adapter, initialPath: `/estimates/${id}`, subscribeEstimateChanges },
    });
    await settle();
    expect(screen.getByRole("button", { name: "문서 제목 편집: 초기 문서" })).toBeInTheDocument();

    receiveChange({ id, kind: "saved", revision: 5 });
    await settle();
    receiveChange({ id, kind: "saved", revision: 6 });
    await settle();
    expect(adapter.readEstimate).toHaveBeenCalledTimes(3);

    newer.resolve(estimate(id, 6, "최신 문서"));
    await settle();
    older.resolve(estimate(id, 5, "오래된 문서"));
    await settle();

    expect(screen.getByRole("button", { name: "문서 제목 편집: 최신 문서" })).toBeInTheDocument();
    view.unmount();
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("ignores an already-applied revision event while the editor is dirty", async () => {
    const id = "b".repeat(32);
    let receiveChange;
    const pendingSave = deferred();
    const subscribeEstimateChanges = vi.fn(async (listener) => {
      receiveChange = listener;
      return vi.fn();
    });
    const adapter = client({
      readEstimate: vi.fn().mockResolvedValue(estimate(id, 4, "초기 문서")),
      updateEstimate: vi.fn().mockReturnValue(pendingSave.promise),
    });
    render(App, {
      props: { client: adapter, initialPath: `/estimates/${id}`, subscribeEstimateChanges },
    });
    await settle();
    await fireEvent.click(screen.getByRole("button", { name: "문서 제목 편집: 초기 문서" }));
    const title = screen.getByRole("textbox", { name: "문서 제목" });
    await fireEvent.input(title, { target: { value: "로컬 편집" } });
    await fireEvent.keyDown(title, { key: "Enter" });
    await settle();

    receiveChange({ id, kind: "saved", revision: 4 });
    await settle();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("저장 중", { selector: ".estimate-save-state" })).toBeInTheDocument();
  });

  it("refreshes the visible estimate list after an external document change", async () => {
    let receiveChange;
    const subscribeEstimateChanges = vi.fn(async (listener) => {
      receiveChange = listener;
      return vi.fn();
    });
    const initial = {
      id: "c".repeat(32), title: "초기 목록", revision: 1, line_count: 1,
      total_won: 1_000, updated_at: "2026-08-04 09:00:00",
    };
    const refreshed = {
      ...initial, id: "d".repeat(32), title: "외부에서 저장한 문서", revision: 2,
      updated_at: "2026-08-04 09:01:00",
    };
    const adapter = client({
      listEstimates: vi.fn().mockResolvedValueOnce([initial]).mockResolvedValueOnce([refreshed]),
    });
    render(App, { props: { client: adapter, initialPath: "/estimates", subscribeEstimateChanges } });
    await settle();
    expect(screen.getByText("초기 목록")).toBeInTheDocument();

    receiveChange({ id: refreshed.id, kind: "saved", revision: refreshed.revision });
    await settle();

    expect(screen.getByText("외부에서 저장한 문서")).toBeInTheDocument();
    expect(screen.queryByText("초기 목록")).not.toBeInTheDocument();
  });

  it("preserves dirty edits on an external save and leaves a deleted active document safely", async () => {
    const id = "b".repeat(32);
    let receiveChange;
    const subscribeEstimateChanges = vi.fn(async (listener) => {
      receiveChange = listener;
      return vi.fn();
    });
    const pendingSave = deferred();
    const adapter = client({
      readEstimate: vi.fn().mockResolvedValue(estimate(id, 4, "현재 문서")),
      updateEstimate: vi.fn().mockReturnValue(pendingSave.promise),
    });
    render(App, {
      props: { client: adapter, initialPath: `/estimates/${id}`, subscribeEstimateChanges },
    });
    await settle();

    await fireEvent.click(screen.getByRole("button", { name: "문서 제목 편집: 현재 문서" }));
    const title = screen.getByRole("textbox", { name: "문서 제목" });
    await fireEvent.input(title, { target: { value: "내 편집본" } });
    await fireEvent.blur(title);
    await tick();
    receiveChange({ id, kind: "saved", revision: 5 });
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("현재 편집본은 유지");
    expect(screen.getByRole("button", { name: "문서 제목 편집: 내 편집본" })).toBeInTheDocument();
    expect(adapter.readEstimate).toHaveBeenCalledTimes(1);

    receiveChange({ id, kind: "deleted", revision: null });
    await settle();
    expect(screen.getByRole("heading", { name: "문서 작성" })).toBeInTheDocument();
  });

  it("restores the durable Data route and replays queued work from the banner", async () => {
    const adapter = client({
      loadDesktopView: vi.fn().mockResolvedValue({ route: "data", path: "/data" }),
      getReconciliationStatus: vi.fn().mockResolvedValue({ state: "queued", online: true, queued_count: 2, conflicts: [] }),
      replayPendingChanges: vi.fn().mockResolvedValue({ state: "idle", online: true, queued_count: 0, conflicts: [] }),
    });
    render(App, { props: { client: adapter, initialPath: "/" } });
    await settle();
    await settle();

    expect(screen.getByRole("heading", { name: "데이터 상태" })).toBeInTheDocument();
    expect(screen.getByText(/2건의 변경사항/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "다시 확인" }));
    await settle();

    expect(adapter.replayPendingChanges).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("동기화 대기 중")).not.toBeInTheDocument();
    expect(adapter.saveDesktopView).toHaveBeenCalledWith({ route: "data", path: "/data" });
  });
});
