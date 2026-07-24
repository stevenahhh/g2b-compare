import { describe, expect, it, vi } from "vitest";

import {
  createLatestStateWriter,
  createRouter,
  matchRoute,
  restoredSearch,
  shouldHandleNavigation,
} from "./router.js";

describe("history router", () => {
  it("never overwrites a search edited while persisted state is loading", () => {
    expect(restoredSearch("new edit", true, { search: "stale value" })).toBe("new edit");
    expect(restoredSearch("", false, { search: "saved value" })).toBe("saved value");
  });

  it("serializes state writes and keeps the latest queued edit", async () => {
    const releases = [];
    const writes = [];
    const write = vi.fn((value) => {
      writes.push(value);
      return new Promise((resolve) => releases.push(resolve));
    });
    const save = createLatestStateWriter(write);

    const first = save({ search: "a" });
    save({ search: "ab" });
    save({ search: "abc" });
    expect(writes).toEqual([{ search: "a" }]);

    releases.shift()();
    await vi.waitFor(() => expect(writes).toEqual([{ search: "a" }, { search: "abc" }]));
    releases.shift()();
    await first;
  });

  it("continues after a failed state write", async () => {
    const write = vi.fn()
      .mockRejectedValueOnce(new Error("storage unavailable"))
      .mockResolvedValueOnce(undefined);
    const save = createLatestStateWriter(write);

    await save({ search: "first" });
    await save({ search: "second" });
    expect(write).toHaveBeenNthCalledWith(2, { search: "second" });
  });

  it("matches only the four core routes and rejects malformed IDs", () => {
    expect(matchRoute("/")).toEqual({ name: "catalog", path: "/" });
    expect(matchRoute("/estimates")).toEqual({ name: "estimates", path: "/estimates" });
    expect(matchRoute("/estimates/a%20b")).toEqual({
      name: "estimate",
      path: "/estimates/a%20b",
      params: { id: "a b" },
    });
    expect(matchRoute("/data")).toEqual({ name: "data", path: "/data" });
    expect(matchRoute("/estimates/%")).toBeNull();
    expect(matchRoute("/live")).toBeNull();
    expect(matchRoute("/priority")).toBeNull();
    expect(matchRoute("/sync")).toBeNull();
  });

  it("updates from popstate and never intercepts legacy links", () => {
    let popstate;
    const windowObject = {
      location: { origin: "http://example.test", pathname: "/", search: "", hash: "" },
      history: {
        pushState: vi.fn((_state, _title, path) => {
          windowObject.location.pathname = path;
        }),
        replaceState: vi.fn(),
      },
      addEventListener: vi.fn((name, listener) => {
        if (name === "popstate") popstate = listener;
      }),
      removeEventListener: vi.fn(),
    };
    const routes = [];
    const router = createRouter((route) => routes.push(route), windowObject);

    expect(router.navigate("/estimates")).toBe(true);
    windowObject.location.pathname = "/data";
    popstate();
    expect(routes.map((route) => route.name)).toEqual(["catalog", "estimates", "data"]);

    const click = { button: 0, defaultPrevented: false, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
    expect(shouldHandleNavigation(click, { dataset: {}, href: "http://example.test/live", target: "" }, windowObject)).toBe(false);
    expect(shouldHandleNavigation(click, { dataset: { spaLink: "" }, href: "http://example.test/data", target: "" }, windowObject)).toBe(true);
    router.destroy();
  });
});
