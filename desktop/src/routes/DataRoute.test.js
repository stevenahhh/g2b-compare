import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import DataRoute from "./DataRoute.svelte";

const status = {
  company_count: 3,
  product_count: 12,
  relation_count: 4,
  option_row_count: 7,
  unique_option_count: 5,
  pending_api_target_count: 2,
  pending_site_product_count: 1,
  ready: true,
  readiness: "ready",
  error: null,
};

function client(overrides = {}) {
  return {
    getDataStatus: vi.fn().mockResolvedValue(structuredClone(status)),
    runDataSync: vi.fn().mockResolvedValue({ state: "complete", stage: null, error: null }),
    runDataDiagnostics: vi.fn().mockResolvedValue({ state: "passed", checked_at: "2026-08-04T09:00:00Z", code: null }),
    openProduct: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

afterEach(() => cleanup());

describe("data status route", () => {
  it("renders all seven legacy counts and retains them behind a safe refresh error", async () => {
    const adapter = client({
      getDataStatus: vi.fn()
        .mockResolvedValueOnce(structuredClone(status))
        .mockRejectedValueOnce(new Error("serviceKey=DO-NOT-LEAK raw provider body")),
    });
    render(DataRoute, { props: { client: adapter } });
    await settle();

    const counts = screen.getByRole("region", { name: "데이터 개수" });
    for (const label of ["업체", "주품목", "관계", "옵션 행", "고유 옵션", "API 수집 대기", "사이트 수집 대기"]) {
      expect(within(counts).getByText(label)).toBeInTheDocument();
    }
    expect(within(counts).getByText("12")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("데이터 작업을 완료하지 못했습니다");
    expect(screen.queryByText(/DO-NOT-LEAK|provider body/)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "마지막으로 확인된 데이터 개수" })).toHaveTextContent("12");
  });

  it("runs sync and diagnostics only from their explicit actions", async () => {
    const adapter = client();
    render(DataRoute, { props: { client: adapter } });
    await settle();

    expect(adapter.runDataSync).not.toHaveBeenCalled();
    expect(adapter.runDataDiagnostics).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole("button", { name: "데이터 동기화" }));
    await settle();
    expect(adapter.runDataSync).toHaveBeenCalledTimes(1);
    expect(screen.getByText("데이터 동기화를 완료했습니다.")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "연결 진단" }));
    await settle();
    expect(adapter.runDataDiagnostics).toHaveBeenCalledTimes(1);
    expect(screen.getByText("연결 및 로컬 데이터 진단을 통과했습니다.")).toBeInTheDocument();
  });
});
