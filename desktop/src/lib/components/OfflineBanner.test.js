import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import OfflineBanner from "./OfflineBanner.svelte";

afterEach(() => cleanup());

describe("offline reconciliation banner", () => {
  it("reports durable queued work and exposes an explicit replay action", async () => {
    const onRetry = vi.fn();
    render(OfflineBanner, {
      props: {
        status: { state: "queued", online: true, queued_count: 3, conflicts: [] },
        onRetry,
        onResolve: vi.fn(),
      },
    });

    expect(screen.getByText("동기화 대기 중")).toBeInTheDocument();
    expect(screen.getByText(/3건의 변경사항/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "다시 확인" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("offers both deterministic resolutions for every retained conflict", async () => {
    const onResolve = vi.fn();
    render(OfflineBanner, {
      props: {
        status: {
          state: "conflict", online: true, queued_count: 1,
          conflicts: [{ sequence: 11, entity_id: "estimate-11", reason_code: "revision-conflict" }],
        },
        onRetry: vi.fn(),
        onResolve,
      },
    });

    expect(screen.getByText("동기화 충돌 확인 필요")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "원격본 사용" }));
    await fireEvent.click(screen.getByRole("button", { name: "로컬 변경 다시 적용" }));
    expect(onResolve.mock.calls).toEqual([[11, "use-remote"], [11, "keep-local"]]);
  });
});
