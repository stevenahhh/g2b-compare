import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { launchApp } from "../e2e/native-workflow.helpers.js";

const evidenceDirectory = path.resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "task-12"
);

test("built renderer exposes only the hardened five-key bridge", async () => {
  await mkdir(evidenceDirectory, { recursive: true });
  const { application, page } = await launchApp();
  try {
    const bridgeKeys = await page.evaluate(() =>
      Object.keys(window.estimator).sort()
    );
    expect(bridgeKeys).toEqual([
      "dialog",
      "export",
      "getBuildInfo",
      "import",
      "readSeed"
    ]);
    const buildInfo = await page.evaluate(() => window.estimator.getBuildInfo());
    expect(buildInfo.ok).toBe(true);
    if (!buildInfo.ok) {
      throw new TypeError(buildInfo.error.code);
    }
    expect(buildInfo.value.sandboxed).toBe(true);
    expect(buildInfo.value.contextIsolated).toBe(true);
    expect(buildInfo.value.unsigned).toBe(true);
    expect(await page.evaluate(() => typeof Reflect.get(globalThis, "require")))
      .toBe("undefined");

    await page.getByTestId("open-legacy-workflow").click();
    await expect(page.getByTestId("legacy-workflow")).toBeVisible();
    await page.getByTestId("open-native-workflow").click();
    await expect(page.getByTestId("native-workflow")).toBeVisible();
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-12-electron-1440.png"),
      fullPage: true
    });
    await writeFile(
      path.join(evidenceDirectory, "task-12-electron-runtime.json"),
      `${JSON.stringify(
        {
          url: page.url(),
          bridgeKeys,
          sandboxed: buildInfo.value.sandboxed,
          contextIsolated: buildInfo.value.contextIsolated,
          unsigned: buildInfo.value.unsigned,
          nativeLegacyRoundTrip: true
        },
        null,
        2
      )}\n`,
      "utf8"
    );
  } finally {
    await application.close();
  }
});
