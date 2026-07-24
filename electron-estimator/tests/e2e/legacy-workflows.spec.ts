import { expect, test } from "@playwright/test";
import {
  mkdir,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import { _electron as electron } from "playwright";
import {
  excelNumber,
  expectNoPublishedPair,
  expectNoSidecar,
  sha256,
  useDialogPaths
} from "./legacy-workflows.helpers.js";

const WORKSPACE_ROOT = path.resolve("..");
const DATASET_ROOT = path.join(WORKSPACE_ROOT, "dataset");
const EVIDENCE_ROOT = path.resolve(
  process.env.EVIDENCE_DIR ??
    path.join(
      WORKSPACE_ROOT,
      ".omo",
      "evidence",
      "electron-estimator",
      "task-16"
    )
);
const CASES = [
  {
    profile: "A",
    source: "250725-전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 내역서.xlsx",
    sha256: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    capacity: 16,
    layout: "13 + 3",
    totalWon: 39_149_530,
    totalSheet: "원가계산서",
    totalCell: "E30"
  },
  {
    profile: "B",
    source: "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx",
    sha256: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    capacity: 9,
    layout: "4개 위치 · 3개 비교견적",
    totalWon: 20_284_000,
    totalSheet: "원가",
    totalCell: "D25"
  },
  {
    profile: "C",
    source: "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx",
    sha256: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    capacity: 24,
    layout: "1개 위치 · 3개 비교견적",
    totalWon: 65_854_000,
    totalSheet: "원가",
    totalCell: "D25"
  }
] as const;

test.beforeAll(async () => {
  await mkdir(EVIDENCE_ROOT, { recursive: true });
});

test("all pinned profiles import, validate and publish exact paired exports", async () => {
  test.setTimeout(240_000);
  const actions: object[] = [];
  for (const fixture of CASES) {
    const source = path.join(DATASET_ROOT, fixture.source);
    const output = path.join(
      EVIDENCE_ROOT,
      `profile-${fixture.profile}_검토초안_미재계산.xlsx`
    );
    const report = output.replace(/[.]xlsx$/u, ".validation.json");
    await Promise.all([rm(output, { force: true }), rm(report, { force: true })]);
    const before = await sha256(source);
    const application = await electron.launch({ args: ["dist/main/index.js"] });
    const page = await application.firstWindow();
    try {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.getByTestId("open-legacy-workflow").click();
      await useDialogPaths(application, source, output);
      await page.getByTestId("import-legacy").click();

      const workflow = page.getByTestId("legacy-workflow");
      await expect(workflow).toHaveAttribute("data-profile", fixture.profile);
      await expect(workflow).toHaveAttribute(
        "data-source-sha256",
        fixture.sha256
      );
      await expect(page.getByTestId("profile-capacity")).toHaveText(
        String(fixture.capacity)
      );
      await expect(page.getByTestId("profile-layout")).toContainText(
        fixture.layout
      );
      await expect(page.getByTestId("preview-total")).toHaveAttribute(
        "data-won",
        String(fixture.totalWon)
      );
      await expect(page.getByTestId("legacy-validation")).toContainText(
        "내보내기 가능"
      );
      if (fixture.profile === "C") {
        await expect(page.getByTestId("inherited-warning")).toContainText(
          "U13:U17"
        );
        await expect(page.getByTestId("canonical-correction")).toContainText(
          "자동 교정하지 않음"
        );
      }

      const firstCell = page.locator('[data-testid="legacy-cell-input"]').first();
      const secondCell = page.locator('[data-testid="legacy-cell-input"]').nth(1);
      const originalSecondValue = await secondCell.inputValue();
      await firstCell.focus();
      await firstCell.press("ArrowDown");
      await expect(secondCell).toBeFocused();
      await secondCell.dispatchEvent("compositionstart");
      await secondCell.fill("한글");
      await secondCell.press("ArrowDown");
      await expect(secondCell).toBeFocused();
      await secondCell.dispatchEvent("compositionend");
      await secondCell.fill(originalSecondValue);

      const exportButton = page.getByTestId("export-legacy");
      await exportButton.click();
      const confirmation = page.getByTestId("legacy-export-confirmation");
      await expect(confirmation).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(exportButton).toBeFocused();
      await exportButton.click();
      await expect(page.getByTestId("legacy-export-ack")).not.toBeChecked();
      await page.getByTestId("legacy-export-ack").check();
      await page.getByTestId("confirm-legacy-export").click();
      await expect(page.getByTestId("legacy-export-result")).toContainText(
        "검증 파일 쌍 저장 완료"
      );
      await expect(exportButton).toBeFocused();

      const workbook = new ExcelJS.Workbook();
      await workbook.xlsx.load(await readFile(output));
      expect(excelNumber(
        workbook.getWorksheet(fixture.totalSheet)?.getCell(fixture.totalCell)
          .value
      )).toBe(fixture.totalWon);
      const validation: unknown = JSON.parse(await readFile(report, "utf8"));
      expect(validation).toMatchObject({
        scope: { profile_id: fixture.profile },
        output: { formula_recalculated: false },
        validation: { status: "pass" }
      });
      expect(await sha256(source)).toBe(before);
      await page.screenshot({
        path: path.join(EVIDENCE_ROOT, `profile-${fixture.profile}.png`),
        fullPage: true
      });
      actions.push({
        profile: fixture.profile,
        sourceSha256Before: before,
        sourceSha256After: await sha256(source),
        totalWon: fixture.totalWon,
        pairedFiles: [path.basename(output), path.basename(report)]
      });
    } finally {
      await application.close();
    }
  }
  await writeFile(
    path.join(EVIDENCE_ROOT, "task-16-legacy-workflows.json"),
    JSON.stringify({ scenarios: actions }, null, 2),
    "utf8"
  );
});

test("blocks unsafe exports with exact errors and publishes file0", async () => {
  test.setTimeout(120_000);
  const sourceA = path.join(DATASET_ROOT, CASES[0].source);
  const sourceB = path.join(DATASET_ROOT, CASES[1].source);
  const blockedOutput = path.join(
    EVIDENCE_ROOT,
    "blocked_검토초안_미재계산.xlsx"
  );
  await rm(blockedOutput, { force: true });
  await rm(blockedOutput.replace(/[.]xlsx$/u, ".validation.json"), {
    force: true
  });
  const sourceABefore = await sha256(sourceA);

  const application = await electron.launch({ args: ["dist/main/index.js"] });
  const page = await application.firstWindow();
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByTestId("open-legacy-workflow").click();
    await useDialogPaths(application, sourceA, blockedOutput);
    await page.getByTestId("import-legacy").click();

    await page.getByTestId("legacy-item-count").fill("17");
    await expect(page.getByTestId("legacy-validation")).toContainText(
      "PROFILE_CAPACITY_EXCEEDED"
    );
    await expect(page.getByTestId("export-legacy")).toBeDisabled();
    await expectNoPublishedPair(blockedOutput);

    await page.getByTestId("legacy-item-count").fill("14");
    await expect(page.getByTestId("legacy-validation")).toContainText(
      "GROUP_BOUNDARY_BREACH"
    );
    await expect(page.getByTestId("export-legacy")).toBeDisabled();
    await expectNoPublishedPair(blockedOutput);

    await page.getByTestId("legacy-item-count").fill("16");
    const exportButton = page.getByTestId("export-legacy");
    await exportButton.click();
    await expect(page.getByTestId("confirm-legacy-export")).toBeDisabled();
    await expect(page.getByTestId("legacy-export-error")).toContainText(
      "DISCLAIMER_REQUIRED"
    );
    await expectNoPublishedPair(blockedOutput);
    await page.keyboard.press("Escape");

    await useDialogPaths(application, sourceA, sourceA);
    await exportButton.click();
    await page.getByTestId("legacy-export-ack").check();
    await page.getByTestId("confirm-legacy-export").click();
    await expect(page.getByTestId("legacy-export-result")).toContainText(
      "SOURCE_OVERWRITE_FORBIDDEN"
    );
    expect(await sha256(sourceA)).toBe(sourceABefore);
    await expectNoSidecar(sourceA);

    await useDialogPaths(application, sourceB, blockedOutput);
    await page.getByTestId("import-legacy").click();
    await page
      .locator('[data-cell-key="단가조사!H5"]')
      .fill("");
    await expect(page.getByTestId("legacy-validation")).toContainText(
      "COMPARISON_REQUIRED"
    );
    await expect(page.getByTestId("export-legacy")).toBeDisabled();
    await expectNoPublishedPair(blockedOutput);
    await page.screenshot({
      path: path.join(EVIDENCE_ROOT, "task-16-legacy-workflows-error.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});
