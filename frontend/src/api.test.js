import { describe, expect, it, vi } from "vitest";

import { requestJson } from "./api.js";

describe("API client", () => {
  it("marks rejected fetches as offline", async () => {
    const fetchImplementation = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(requestJson("/api/data/status", {}, fetchImplementation)).rejects.toMatchObject({
      name: "ApiError",
      offline: true,
      status: 0,
    });
  });

  it("preserves an HTTP failure as a modal-safe error", async () => {
    const fetchImplementation = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      headers: { get: () => "application/json" },
      json: vi.fn().mockResolvedValue({ error: "data-unavailable" }),
    });
    await expect(requestJson("/api/data/status", {}, fetchImplementation)).rejects.toMatchObject({
      name: "ApiError",
      message: "data-unavailable",
      status: 503,
      offline: false,
      body: { error: "data-unavailable" },
    });
  });
});
