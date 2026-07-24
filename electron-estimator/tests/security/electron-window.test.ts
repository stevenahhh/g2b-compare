import { mkdtemp, realpath, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, type ElectronApplication } from "playwright";
import { afterEach, describe, expect, it } from "vitest";
import {
  APP_CSP,
  APP_ORIGIN,
  resolveAppAsset
} from "../../src/main/protocol.js";
import { createMainWindowOptions } from "../../src/main/window.js";

let runningApp: ElectronApplication | undefined;

afterEach(async () => {
  if (runningApp !== undefined) {
    await runningApp.close();
    runningApp = undefined;
  }
});

describe("Given the Electron desktop host", () => {
  it("uses the required BrowserWindow isolation options when creating the window", () => {
    const options = createMainWindowOptions("C:\\app\\preload\\index.js");

    expect(options.webPreferences).toMatchObject({
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      webSecurity: true,
      allowRunningInsecureContent: false
    });
  });

  it(
    "loads app://app with an isolated estimator bridge when launched by real Electron",
    async () => {
      runningApp = await electron.launch({
        args: [path.resolve("dist/main/index.js")],
        cwd: process.cwd(),
        timeout: 15_000
      });

      const page = await runningApp.firstWindow({ timeout: 15_000 });
      await page.waitForLoadState("domcontentloaded");
      const runtime = await page.evaluate(async () => {
        const estimator = Reflect.get(globalThis, "estimator");
        const getBuildInfo =
          typeof estimator === "object" && estimator !== null
            ? Reflect.get(estimator, "getBuildInfo")
            : undefined;
        const buildInfo =
          typeof getBuildInfo === "function"
            ? await Reflect.apply(getBuildInfo, estimator, [])
            : null;
        const response = await fetch(globalThis.location.href);
        return {
          origin: globalThis.location.origin,
          requireType: typeof Reflect.get(globalThis, "require"),
          processType: typeof Reflect.get(globalThis, "process"),
          estimatorKeys:
            typeof estimator === "object" && estimator !== null
              ? Object.keys(estimator).sort()
              : [],
          estimatorFrozen:
            typeof estimator === "object" &&
            estimator !== null &&
            Object.isFrozen(estimator),
          csp: response.headers.get("content-security-policy"),
          buildInfo
        };
      });

      expect(runtime).toEqual({
        origin: APP_ORIGIN,
        requireType: "undefined",
        processType: "undefined",
        estimatorKeys: [
          "dialog",
          "export",
          "getBuildInfo",
          "import",
          "readSeed"
        ],
        estimatorFrozen: true,
        csp: APP_CSP,
        buildInfo: expect.objectContaining({
          ok: true,
          value: expect.objectContaining({
            sandboxed: true,
            contextIsolated: true
          })
        })
      });
    },
    30_000
  );
});

describe("Given an app protocol asset request", () => {
  it("returns the canonical renderer file when the URL stays in the bundle", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "estimator-protocol-"));
    const index = path.join(root, "index.html");
    await writeFile(index, "<!doctype html>", "utf8");

    const resolved = await resolveAppAsset(root, "app://app/");

    expect(resolved).toBe(await realpath(index));
  });

  it.each([
    "app://other/index.html",
    "https://app/index.html",
    "app://app/%2e%2e/secret.txt",
    "app://app/%5c..%5csecret.txt",
    "app://app/C:%5csecret.txt"
  ])("rejects non-local or traversal URL %s", async (url) => {
    const root = await mkdtemp(path.join(tmpdir(), "estimator-protocol-"));

    await expect(resolveAppAsset(root, url)).resolves.toBeNull();
  });

  it("defines a restrictive local-only CSP", () => {
    expect(APP_CSP).toContain("default-src 'none'");
    expect(APP_CSP).toContain("script-src 'self'");
    expect(APP_CSP).toContain("style-src 'self'");
    expect(APP_CSP).toContain("font-src 'self'");
    expect(APP_CSP).toContain("img-src 'self'");
    expect(APP_CSP).toContain("connect-src 'self'");
    expect(APP_CSP).not.toContain("unsafe-eval");
    expect(APP_CSP).not.toMatch(/https?:/u);
  });
});
