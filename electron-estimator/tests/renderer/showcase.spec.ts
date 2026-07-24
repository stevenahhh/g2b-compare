import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { launchApp } from "../e2e/native-workflow.helpers.js";

const evidenceDirectory = path.resolve(
  process.cwd(),
  "..",
  ".omo",
  "evidence",
  "task-12"
);

test("production native and legacy controls keep the Concept A primitive metrics", async () => {
  await mkdir(evidenceDirectory, { recursive: true });
  const { application, page } = await launchApp();
  try {
    await expect(page.getByTestId("project-id")).toHaveCSS(
      "min-height",
      "44px"
    );
    await expect(page.getByTestId("open-legacy-workflow")).toHaveCSS(
      "min-height",
      "44px"
    );
    await page.getByTestId("open-legacy-workflow").click();
    await expect(page.getByTestId("legacy-workflow")).toBeVisible();
    await expect(page.getByTestId("import-legacy")).toHaveCSS(
      "min-height",
      "44px"
    );
    await expect(page.getByTestId("legal-notice")).toBeVisible();
    await expect(page.getByTestId("unsigned-notice")).toBeVisible();
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-12-production-primitives.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});
