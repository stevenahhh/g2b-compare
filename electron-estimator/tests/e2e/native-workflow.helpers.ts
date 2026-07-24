import type {
  ElectronApplication,
  Locator,
  Page
} from "@playwright/test";
import { _electron as electron, expect } from "@playwright/test";
import { build } from "esbuild";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import {
  lowerAuthenticFixture,
  noComparableFixture,
  selectedKoreaNetFixture,
  type CandidateFixture
} from "./native-workflow.fixtures.js";

export {
  lowerAuthenticFixture,
  noComparableFixture,
  selectedKoreaNetFixture
};

const HASH_C = "c".repeat(64);
const TEST_MAIN_ROOT = path.resolve(
  `.test-dist-${String(process.pid)}-${process.env.TEST_WORKER_INDEX ?? "0"}`
);
const TEST_MAIN_ENTRY = path.join(TEST_MAIN_ROOT, "main", "index.js");

export async function launchApp(): Promise<{
  readonly application: ElectronApplication;
  readonly page: Page;
}> {
  const application = await electron.launch({ args: ["dist/main/index.js"] });
  const page = await application.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator('[data-testid="native-workflow"]')).toBeVisible();
  return { application, page };
}

export async function launchTrustedFixtureApp(): Promise<{
  readonly application: ElectronApplication;
  readonly page: Page;
}> {
  await rm(TEST_MAIN_ROOT, { force: true, recursive: true });
  await build({
    bundle: true,
    entryPoints: ["tests/e2e/native-workflow-test-main.ts"],
    external: ["electron", "exceljs"],
    format: "esm",
    outfile: TEST_MAIN_ENTRY,
    platform: "node",
    sourcemap: false,
    target: "node24"
  });
  const application = await electron.launch({ args: [TEST_MAIN_ENTRY] });
  const page = await application.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator('[data-testid="native-workflow"]')).toBeVisible();
  return { application, page };
}

export async function cleanupTrustedFixtureApp(): Promise<void> {
  await rm(TEST_MAIN_ROOT, { force: true, recursive: true });
}

export async function useSavePath(
  application: ElectronApplication,
  destination: string | null
): Promise<void> {
  await mkdir(path.dirname(destination ?? path.resolve("test-results", "cancelled")), {
    recursive: true
  });
  await application.evaluate(
    ({ dialog }, selectedPath) => {
      Object.defineProperty(dialog, "showSaveDialog", {
        configurable: true,
        value: async () =>
          selectedPath === null
            ? { canceled: true, filePath: undefined }
            : { canceled: false, filePath: selectedPath }
      });
    },
    destination
  );
}

export async function fillProject(page: Page): Promise<void> {
  await page.getByTestId("project-id").fill("native-e2e");
  await page.getByTestId("project-name").fill("CCTV LAN FIBER 실무 검토");
  await page.getByTestId("prepared-on").fill("2026-07-23");
  await page.getByTestId("context-issuer").fill("내부 검토자");
  await page.getByTestId("context-regime").selectOption("national");
  await page.getByTestId("context-date").fill("2026-07-23");
  await page.getByTestId("context-project-type").fill("CCTV/LAN/FIBER");
  await page.getByTestId("context-contract-level").selectOption("general");
  await page.getByTestId("context-amount-basis").fill("재료비 및 노무비 참고");
  await page.getByTestId("context-supplied-materials").selectOption("mixed");
  await page.getByTestId("context-pricing-method").fill("2026 공식 기준");
  await page.getByTestId("context-vat-status").selectOption("unknown");
}

export async function addBlankRow(
  page: Page,
  field: "CCTV" | "LAN" | "FIBER",
  values: {
    readonly itemName: string;
    readonly specification: string;
    readonly unit: string;
    readonly quantity: string;
  }
): Promise<Locator> {
  await page.getByTestId("add-row").click();
  const row = page.locator('[data-testid="estimate-row"]').last();
  await row.locator('[data-field="field"]').selectOption(field);
  await row.locator('[data-field="itemName"]').fill(values.itemName);
  await row.locator('[data-field="specification"]').fill(values.specification);
  await row.locator('[data-field="unit"]').fill(values.unit);
  await row.locator('[data-field="quantity"]').fill(values.quantity);
  await row.click();
  return row;
}

export async function fillUserQuote(page: Page, price: string): Promise<void> {
  await page.getByTestId("source-kind").selectOption("user_quote");
  await page.getByTestId("quote-id").fill(`quote-${price}`);
  await page.getByTestId("supplier-name").fill("사용자 입력 업체");
  await page.getByTestId("source-unit-price").fill(price);
  await page.getByTestId("quote-date").fill("2026-07-23");
  await page.getByTestId("document-sha256").fill(HASH_C);
}

export async function runSelector(
  page: Page,
  fixture: CandidateFixture
): Promise<void> {
  await page.getByTestId("source-kind").selectOption("sourced_observation");
  await page.getByTestId("comparison-group").fill(fixture.comparisonGroup);
  await page.getByTestId("run-selector").click();
}

export async function confirmExport(page: Page): Promise<void> {
  await page.getByTestId("export-workbook").click();
  await expect(page.getByTestId("export-confirmation")).toBeVisible();
  await page.getByTestId("export-warning-ack").check();
  await page.getByTestId("confirm-export").click();
  await expect(page.getByTestId("export-result")).toContainText("저장 완료");
}
