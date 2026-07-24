import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { addBlankRow, launchApp } from "./native-workflow.helpers.js";

const evidenceDirectory = path.resolve(
  process.env.EVIDENCE_DIR ??
    path.join(
      process.cwd(),
      "..",
      ".omo",
      "evidence",
      "electron-estimator",
      "task-14"
    )
);

test("1024 native workflow keeps the Carbon rail and accessible inspector overlay", async () => {
  await mkdir(evidenceDirectory, { recursive: true });
  const { application, page } = await launchApp();
  try {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.reload();
    await expect(page.getByTestId("native-workflow")).toBeVisible();
    const left = await page.getByTestId("left-rail").boundingBox();
    expect(left?.width).toBe(56);
    await expect(page.getByTestId("provenance-inspector")).toHaveAttribute(
      "aria-hidden",
      "true"
    );

    await addBlankRow(page, "LAN", {
      itemName: "반응형 확인",
      specification: "CAT.6",
      unit: "m",
      quantity: "1"
    });
    const trigger = page.getByTestId("open-inspector");
    await trigger.click();
    const inspector = page.getByTestId("provenance-inspector");
    const close = page.getByTestId("close-inspector");
    await expect(inspector).toHaveAttribute("role", "dialog");
    await expect(inspector).toHaveAttribute("aria-modal", "true");
    await expect(inspector).toHaveAttribute("aria-hidden", "false");
    await expect(close).toBeFocused();

    const box = await inspector.boundingBox();
    expect(box?.width).toBe(360);
    expect(box?.x).toBe(664);
    const notices = page.locator(".workbench-notices");
    const noticesBox = await notices.boundingBox();
    expect(noticesBox).not.toBeNull();
    expect(box).not.toBeNull();
    expect((noticesBox?.x ?? 0) + (noticesBox?.width ?? 0)).toBeLessThanOrEqual(
      box?.x ?? 0
    );
    expect(
      await notices.evaluate(
        (node) =>
          getComputedStyle(node).gridTemplateColumns.split(" ").length
      )
    ).toBe(1);
    for (const testId of ["legal-notice", "unsigned-notice"]) {
      expect(
        await page.getByTestId(testId).evaluate(
          (node) =>
            node.scrollWidth <= node.clientWidth &&
            node.scrollHeight <= node.clientHeight
        )
      ).toBe(true);
    }
    await page.keyboard.press("Tab");
    expect(
      await inspector.evaluate((node) => node.contains(document.activeElement))
    ).toBe(true);
    await page
      .locator('[data-grid-row="0"][data-grid-column="0"]')
      .evaluate((node) => node.focus());
    expect(
      await inspector.evaluate((node) => node.contains(document.activeElement))
    ).toBe(true);

    await page.screenshot({
      path: path.join(
        evidenceDirectory,
        "task-14-native-workflow-1024.png"
      ),
      fullPage: true
    });
    await writeFile(
      path.join(evidenceDirectory, "task-14-native-workflow-1024.json"),
      `${JSON.stringify(
        {
          viewport: { width: 1024, height: 768 },
          leftRailPx: left?.width,
          inspectorPx: box?.width,
          inspectorX: box?.x,
          modalRole: await inspector.getAttribute("role"),
          ariaModal: await inspector.getAttribute("aria-modal"),
          focusStayedInside: true,
          backgroundFocusBlocked: true
        },
        null,
        2
      )}\n`,
      "utf8"
    );

    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
    await expect(page.getByTestId("provenance-inspector")).toHaveAttribute(
      "aria-hidden",
      "true"
    );
  } finally {
    await application.close();
  }
});
