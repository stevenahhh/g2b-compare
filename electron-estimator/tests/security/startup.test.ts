import { describe, expect, it, vi } from "vitest";
import { createVerifiedWindow } from "../../src/main/startup.js";

describe("Given Electron host startup", () => {
  it("verifies official resources before creating the BrowserWindow", async () => {
    const order: string[] = [];
    const window = {};

    const result = await createVerifiedWindow("C:\\app\\resources", {
      assertOfficialDataReady: async (resourceRoot) => {
        expect(resourceRoot).toBe("C:\\app\\resources");
        order.push("official-ready");
      },
      createWindow: () => {
        order.push("window-created");
        return window;
      }
    });

    expect(result).toBe(window);
    expect(order).toEqual(["official-ready", "window-created"]);
  });

  it("does not create the BrowserWindow when official verification rejects", async () => {
    const createWindow = vi.fn(() => ({}));

    await expect(
      createVerifiedWindow("C:\\app\\resources", {
        assertOfficialDataReady: async () => {
          throw new Error("official hash drift");
        },
        createWindow
      })
    ).rejects.toThrow("official hash drift");
    expect(createWindow).not.toHaveBeenCalled();
  });
});
