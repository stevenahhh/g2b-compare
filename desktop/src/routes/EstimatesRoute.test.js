import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import EstimatesRoute from "./EstimatesRoute.svelte";

const summary = {
  id: "a".repeat(32),
  title: "1-20260804-093000",
  revision: 3,
  line_count: 2,
  total_won: 2_500_000,
  updated_at: "2026-08-04 09:30:00",
};

function client(overrides = {}) {
  return {
    listEstimates: vi.fn().mockResolvedValue([summary]),
    createEstimate: vi.fn(),
    readEstimate: vi.fn(),
    updateEstimate: vi.fn(),
    deleteEstimate: vi.fn().mockResolvedValue(undefined),
    loadEstimateView: vi.fn().mockResolvedValue(null),
    saveEstimateView: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await tick();
}

afterEach(() => cleanup());

describe("estimate list route", () => {
  it("lists, opens, and confirms deletion of saved documents", async () => {
    const adapter = client();
    const navigate = vi.fn();
    render(EstimatesRoute, { props: { client: adapter, onNavigate: navigate } });
    await settle();

    expect(screen.getByText("1-20260804-093000")).toBeInTheDocument();
    expect(screen.getByText("2개 품목 · 합계 2,500,000원")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: /1-20260804-093000/ }));
    await settle();
    expect(adapter.saveEstimateView).toHaveBeenCalledWith({ active_estimate_id: summary.id });
    expect(navigate).toHaveBeenCalledWith(`/estimates/${summary.id}`);

    await fireEvent.click(screen.getByRole("button", { name: "삭제" }));
    expect(screen.getByRole("alertdialog", { name: "문서 삭제" })).toBeInTheDocument();
    await fireEvent.click(screen.getAllByRole("button", { name: "삭제" }).at(-1));
    await settle();
    expect(adapter.deleteEstimate).toHaveBeenCalledWith(summary.id);
    expect(screen.queryByText("1-20260804-093000")).not.toBeInTheDocument();
  });

  it("creates a deterministic empty draft and opens its editor", async () => {
    const id = "b".repeat(32);
    const created = {
      id,
      title: "2-20260804-093005",
      template_sha256: "",
      revision: 1,
      created_at: "2026-08-04 09:30:05",
      updated_at: "2026-08-04 09:30:05",
      lines: [],
    };
    const adapter = client({ createEstimate: vi.fn().mockResolvedValue(created) });
    const navigate = vi.fn();
    render(EstimatesRoute, {
      props: {
        client: adapter,
        onNavigate: navigate,
        createId: () => id,
        now: () => new Date(2026, 7, 4, 9, 30, 5),
      },
    });
    await settle();

    await fireEvent.click(screen.getByRole("button", { name: "새 문서" }));
    await settle();

    expect(adapter.createEstimate).toHaveBeenCalledWith({
      id,
      title: "2-20260804-093005",
      template_sha256: "",
      lines: [],
      comparisons: [],
    });
    expect(navigate).toHaveBeenCalledWith(`/estimates/${id}`);
  });
});
