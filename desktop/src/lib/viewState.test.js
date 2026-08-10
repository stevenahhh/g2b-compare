import { describe, expect, it, vi } from "vitest";

import { createDurableViewStateAdapter, createLatestViewStateWriter } from "./viewState";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

describe("durable view-state adapter", () => {
  it("maps the load/save contract without browser storage", async () => {
    const client = {
      loadDesktopView: vi.fn().mockResolvedValue({ route: "data", path: "/data" }),
      saveDesktopView: vi.fn().mockResolvedValue(undefined),
    };
    const adapter = createDurableViewStateAdapter(client);

    await expect(adapter.load()).resolves.toEqual({ route: "data", path: "/data" });
    await adapter.save({ route: "catalog", path: "/" });

    expect(client.saveDesktopView).toHaveBeenCalledWith({ route: "catalog", path: "/" });
  });

  it("serializes writes and persists the latest queued view without timing waits", async () => {
    const gate = deferred();
    const saved = [];
    let calls = 0;
    const writer = createLatestViewStateWriter({
      load: vi.fn(),
      save: async (state) => {
        saved.push(state);
        calls += 1;
        if (calls === 1) await gate.promise;
      },
    });

    const completion = writer({ route: "catalog", path: "/" });
    await Promise.resolve();
    writer({ route: "estimates", path: "/estimates" });
    writer({ route: "data", path: "/data" });
    gate.resolve();
    await completion;

    expect(saved).toEqual([
      { route: "catalog", path: "/" },
      { route: "data", path: "/data" },
    ]);
  });
});
