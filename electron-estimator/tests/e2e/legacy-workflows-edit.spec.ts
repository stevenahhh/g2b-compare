import { expect, test } from "@playwright/test";
import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { _electron as electron } from "playwright";
import {
  sha256,
  useDialogPaths
} from "./legacy-workflows.helpers.js";

const SOURCE = path.resolve(
  "..",
  "dataset",
  "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx"
);
const EVIDENCE_ROOT = path.resolve(
  process.env.EVIDENCE_DIR ??
    path.join(
      "..",
      ".omo",
      "evidence",
      "electron-estimator",
      "task-16"
    )
);
const OUTPUT = path.join(
  EVIDENCE_ROOT,
  "profile-A-edit_검토초안_미재계산.xlsx"
);
const REPORT = OUTPUT.replace(/[.]xlsx$/u, ".validation.json");

test("an allowlisted GUI edit is published only to the paired draft", async () => {
  await Promise.all([rm(OUTPUT, { force: true }), rm(REPORT, { force: true })]);
  const sourceBefore = await sha256(SOURCE);
  const application = await electron.launch({ args: ["dist/main/index.js"] });
  const page = await application.firstWindow();
  try {
    await page.getByTestId("open-legacy-workflow").click();
    await useDialogPaths(application, SOURCE, OUTPUT);
    await page.getByTestId("import-legacy").click();
    const input = page.locator('[data-testid="legacy-cell-input"]').first();
    const cellKey = await input.getAttribute("data-cell-key");
    expect(cellKey).not.toBeNull();
    await input.fill("CCTV 카메라 검토품");
    await page.getByTestId("export-legacy").click();
    await page.getByTestId("legacy-export-ack").check();
    await page.getByTestId("confirm-legacy-export").click();
    await expect(page.getByTestId("legacy-export-result")).toContainText(
      "검증 파일 쌍 저장 완료"
    );

    const [sheetName, address] = (cellKey ?? "").split("!");
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await readFile(OUTPUT));
    expect(workbook.getWorksheet(sheetName)?.getCell(address ?? "").value).toBe(
      "CCTV 카메라 검토품"
    );
    const report: unknown = JSON.parse(await readFile(REPORT, "utf8"));
    expect(report).toMatchObject({
      output: { formula_recalculated: false },
      validation: { status: "pass" }
    });
    if (typeof report !== "object" || report === null) {
      throw new TypeError("Expected a validation report object");
    }
    expect(Reflect.get(report, "changed_cells")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ sheet: sheetName, address })
      ])
    );
    expect(await sha256(SOURCE)).toBe(sourceBefore);
    expect(await sha256(OUTPUT)).not.toBe(sourceBefore);
  } finally {
    await application.close();
  }
});

test("a pending import cannot replace the native workflow after navigation", async () => {
  const application = await electron.launch({ args: ["dist/main/index.js"] });
  const page = await application.firstWindow();
  try {
    await application.evaluate(({ dialog }) => {
      Object.defineProperty(dialog, "showOpenDialog", {
        configurable: true,
        value: async () => {
          await new Promise((resolve) => setTimeout(resolve, 150));
          return { canceled: true, filePaths: [] };
        }
      });
    });
    await page.getByTestId("open-legacy-workflow").click();
    await page.getByTestId("import-legacy").click();
    await expect(page.getByTestId("import-legacy")).toBeDisabled();
    await page.getByTestId("open-native-workflow").click();
    await expect(page.getByTestId("native-workflow")).toBeVisible();
    await page.waitForTimeout(200);
    await expect(page.getByTestId("native-workflow")).toBeVisible();
    await expect(page.getByTestId("legacy-workflow")).toHaveCount(0);
  } finally {
    await application.close();
  }
});
