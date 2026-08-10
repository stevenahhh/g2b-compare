import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import AppHeader from "./AppHeader.svelte";

afterEach(() => cleanup());

describe("application update control", () => {
  it("offers a discovered update and installs it after confirmation", async () => {
    const downloadAndInstall = vi.fn(async () => undefined);
    const updateClient = {
      check: vi.fn(async () => ({
        version: "0.2.0",
        body: "안정성 개선",
        downloadAndInstall,
      })),
      relaunch: vi.fn(async () => undefined),
    };

    render(AppHeader, { props: { updateClient } });

    await fireEvent.click(
      await screen.findByRole("button", { name: "0.2.0 업데이트" }),
    );
    expect(
      screen.getByText(/사용자 데이터는 유지되며 앱이 다시 시작됩니다/u),
    ).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "설치 후 다시 시작" }));
    expect(downloadAndInstall).toHaveBeenCalledTimes(1);
  });

  it("shows download progress before relaunching the updated app", async () => {
    const relaunch = vi.fn(async () => undefined);
    const updateClient = {
      check: vi.fn(async () => ({
        version: "0.2.0",
        body: null,
        downloadAndInstall: vi.fn(async (onEvent) => {
          onEvent({ event: "Started", data: { contentLength: 200 } });
          onEvent({ event: "Progress", data: { chunkLength: 100 } });
          onEvent({ event: "Finished" });
        }),
      })),
      relaunch,
    };

    render(AppHeader, { props: { updateClient } });
    await fireEvent.click(
      await screen.findByRole("button", { name: "0.2.0 업데이트" }),
    );
    await fireEvent.click(screen.getByRole("button", { name: "설치 후 다시 시작" }));

    expect(await screen.findByText("업데이트 설치 완료")).toBeInTheDocument();
    expect(relaunch).toHaveBeenCalledTimes(1);
  });

  it("shows an update connection error without hiding it in a tooltip", async () => {
    const updateClient = {
      check: vi.fn(async () => {
        throw new Error("network unavailable");
      }),
      relaunch: vi.fn(async () => undefined),
    };

    render(AppHeader, { props: { updateClient } });

    expect(
      await screen.findByText("업데이트 서버에 연결하지 못했습니다."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "업데이트 다시 확인" }),
    ).not.toHaveAttribute("title");
  });
});
