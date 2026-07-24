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

test.beforeAll(async () => {
  await mkdir(evidenceDirectory, { recursive: true });
});

test("1440 production workflows keep the Concept A three-pane contract", async () => {
  const { application, page } = await launchApp();
  try {
    const nativeMetrics = await regionMetrics(page, "provenance-inspector");
    expect(nativeMetrics).toEqual({ left: 224, center: 896, right: 320 });
    await expect(page.getByTestId("koreanet-badge")).toHaveCount(0);
    await expect(page.getByTestId("legal-notice")).toContainText(
      "법적 인증 아님"
    );
    await expect(page.getByTestId("unsigned-notice")).toContainText(
      "코드 서명되지 않은 시험 빌드"
    );

    await page.getByTestId("open-legacy-workflow").click();
    await expect(page.getByTestId("legacy-workflow")).toBeVisible();
    const legacyMetrics = await regionMetrics(page, "legacy-inspector");
    expect(legacyMetrics).toEqual(nativeMetrics);
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-12-workbench-1440.png"),
      fullPage: true
    });
    await writeFile(
      path.join(evidenceDirectory, "task-12-workbench-1440.json"),
      `${JSON.stringify({ native: nativeMetrics, legacy: legacyMetrics }, null, 2)}\n`,
      "utf8"
    );
  } finally {
    await application.close();
  }
});

test("1024 production inspector traps focus and restores its trigger", async () => {
  const { application, page } = await launchApp();
  try {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.reload();
    expect((await page.getByTestId("left-rail").boundingBox())?.width).toBe(56);
    const trigger = page.getByTestId("open-inspector");
    await trigger.click();
    const inspector = page.getByTestId("provenance-inspector");
    const close = page.getByTestId("close-inspector");
    await expect(inspector).toHaveAttribute("role", "dialog");
    await expect(inspector).toHaveAttribute("aria-modal", "true");
    await expect(close).toBeFocused();
    await expect(close).toHaveCSS("outline-width", "3px");

    const box = await inspector.boundingBox();
    expect(box?.width).toBe(360);
    expect(box?.x).toBe(664);
    await page.keyboard.press("Tab");
    expect(
      await inspector.evaluate((node) => node.contains(document.activeElement))
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
    await expect(inspector).toHaveAttribute("aria-hidden", "true");
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-12-workbench-1024.png"),
      fullPage: true
    });
    await writeFile(
      path.join(evidenceDirectory, "task-12-overlay-accessibility.json"),
      `${JSON.stringify(
        {
          leftRailPx: 56,
          inspectorPx: box?.width,
          inspectorX: box?.x,
          focusRestored: true
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

async function regionMetrics(
  page: import("@playwright/test").Page,
  inspectorTestId: "provenance-inspector" | "legacy-inspector"
): Promise<{ readonly left: number; readonly center: number; readonly right: number }> {
  const left = await page.getByTestId("left-rail").boundingBox();
  const center = await page.getByTestId("center-pane").boundingBox();
  const right = await page.getByTestId(inspectorTestId).boundingBox();
  if (left === null || center === null || right === null) {
    throw new TypeError("Expected all Concept A regions to be visible");
  }
  return { left: left.width, center: center.width, right: right.width };
}
