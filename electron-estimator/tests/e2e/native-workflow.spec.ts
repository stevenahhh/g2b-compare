import { expect, test } from "@playwright/test";
import { access, readFile, rm } from "node:fs/promises";
import path from "node:path";
import ExcelJS from "exceljs";
import {
  addBlankRow,
  cleanupTrustedFixtureApp,
  confirmExport,
  fillProject,
  fillUserQuote,
  launchApp,
  launchTrustedFixtureApp,
  lowerAuthenticFixture,
  runSelector,
  selectedKoreaNetFixture,
  useSavePath
} from "./native-workflow.helpers.js";

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

test("Electron launch exposes the native workflow instead of hanging on an ExcelJS dynamic require", async () => {
  const { application, page } = await launchApp();
  try {
    await expect(page.getByTestId("native-workflow")).toBeVisible();
    expect(
      await page.evaluate(() => Object.keys(window.estimator).sort())
    ).toEqual(["dialog", "export", "getBuildInfo", "import", "readSeed"]);
    const catalog = await page.evaluate(() =>
      window.estimator.readSeed({ kind: "native_catalog" })
    );
    expect(catalog.ok, JSON.stringify(catalog)).toBe(true);
    if (catalog.ok && "sourcedProducts" in catalog.value) {
      expect(catalog.value.sourcedProducts).toHaveLength(0);
    }
  } finally {
    await application.close();
  }
});

test("Given a new mixed project When exported Then the actual Electron flow saves a six-sheet workbook", async () => {
  const output = path.join(evidenceDirectory, "task-14-native-workflow.xlsx");
  await rm(output, { force: true });
  const { application, page } = await launchApp();
  await useSavePath(application, output);
  try {
    await fillProject(page);
    await addBlankRow(page, "CCTV", {
      itemName: "4MP 카메라",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "2"
    });
    await fillUserQuote(page, "2000");
    await page.getByTestId("supplier-name").fill("KoreaNet");
    await expect(page.getByTestId("koreanet-badge")).toHaveCount(0);

    await addBlankRow(page, "LAN", {
      itemName: "24포트 스위치",
      specification: "24PORT",
      unit: "EA",
      quantity: "3"
    });
    await page.getByTestId("cost-method").selectOption("three_company_min");
    for (const [slot, price] of [
      ["A", "500"],
      ["B", "500"],
      ["C", "700"]
    ] as const) {
      await page.getByTestId(`quote-${slot}-id`).fill(`quote-${slot}`);
      await page.getByTestId(`quote-${slot}-supplier`).fill(`${slot}사`);
      await page.getByTestId(`quote-${slot}-price`).fill(price);
      await page.getByTestId(`quote-${slot}-date`).fill("2026-07-23");
      await page.getByTestId(`quote-${slot}-sha`).fill("c".repeat(64));
    }

    await page.getByTestId("catalog-search").fill("SMF 2C");
    await page.locator('[data-catalog-kind="market"]').first().click();
    await page.getByTestId("catalog-search").fill("카메라 설치 일반형");
    await page.locator('[data-catalog-kind="productivity"]').first().click();

    await expect(page.getByTestId("export-workbook")).toBeEnabled();
    const preview = await page.getByTestId("preview-total").getAttribute("data-won");
    await confirmExport(page);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await readFile(output));
    expect(workbook.worksheets.map((sheet) => sheet.name)).toEqual([
      "설정",
      "품목",
      "단가",
      "요약",
      "공식단가",
      "출처"
    ]);
    expect(String(workbook.getWorksheet("요약")?.getCell("E9").result)).toBe(
      preview
    );
    expect(workbook.getWorksheet("설정")?.getCell("A10").value).toContain(
      "법적 인증 아님"
    );
    expect(workbook.getWorksheet("설정")?.getCell("A11").value).toContain(
      "코드 서명되지 않은 시험 빌드"
    );
    const sourceSheet = workbook.getWorksheet("출처");
    const userPrices =
      sourceSheet
        ?.getRows(4, Math.max(0, (sourceSheet?.rowCount ?? 3) - 3))
        ?.filter((row) => row.getCell("B").value === "user_entered_price") ?? [];
    expect(userPrices).toHaveLength(4);
    expect(userPrices.every((row) => row.getCell("V").value === "미검증")).toBe(
      true
    );
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-14-native-workflow.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});

test("Given missing source context double count and nonpositive input When reviewed Then export stays blocked with exact Korean errors", async () => {
  const output = test.info().outputPath("must-not-exist.xlsx");
  const { application, page } = await launchApp();
  await useSavePath(application, output);
  try {
    await page.getByTestId("project-id").fill("invalid-native");
    await page.getByTestId("project-name").fill("차단 검증");
    await page.getByTestId("prepared-on").fill("2026-07-23");
    const row = await addBlankRow(page, "CCTV", {
      itemName: "출처 없는 카메라",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "0"
    });
    await row.click();
    await page.getByTestId("catalog-search").fill("SMF 2C");
    await page.locator('[data-catalog-kind="market"]').first().click();
    await page.getByTestId("catalog-search").fill("카메라 설치 일반형");
    await page
      .locator('[data-catalog-apply="productivity"]')
      .first()
      .click();

    const errors = page.getByTestId("validation-errors");
    await expect(errors).toContainText(
      "오류 NON_POSITIVE_INPUT: 수량과 단가는 0보다 커야 함."
    );
    await expect(errors).toContainText(
      "오류 SOURCE_REQUIRED: 적용단가의 출처를 입력해야 함."
    );
    await expect(errors).toContainText(
      "오류 RATE_CONTEXT_REQUIRED: 공식단가에 필요한 요율 문맥을 모두 입력해야 함."
    );
    await expect(errors).toContainText(
      "오류 PRICING_METHOD_CONFLICT: 시장단가와 표준품셈을 한 행에 동시에 적용할 수 없음."
    );
    await expect(page.getByTestId("export-workbook")).toBeDisabled();
    await expect(access(output)).rejects.toThrow();
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-14-native-workflow-error.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});

test("Given authentic sourced candidates When Task8 selects Then KoreaNet is conditional and provenance is byte-exact", async () => {
  const output = path.join(evidenceDirectory, "task-14-koreanet-workflow.xlsx");
  await rm(output, { force: true });
  const { application, page } = await launchTrustedFixtureApp();
  await useSavePath(application, output);
  try {
    await fillProject(page);
    await addBlankRow(page, "CCTV", {
      itemName: "KoreaNet 후보 카메라",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "2"
    });
    await runSelector(page, selectedKoreaNetFixture);
    await expect(page.getByTestId("koreanet-badge")).toBeVisible();
    const selectedDto = await page.getByTestId("selector-dto").textContent();
    for (const label of [
      "제품 ID",
      "업체",
      "단가",
      "단위",
      "규격 snapshot",
      "Source URL",
      "API operation",
      "Observed time",
      "Payload SHA-256",
      "Supplier location evidence",
      "Service area evidence"
    ]) {
      await expect(
        page.locator(`[data-provenance-field="${label}"], [data-evidence-field="${label}"]`)
      ).toBeVisible();
    }

    await addBlankRow(page, "CCTV", {
      itemName: "더 싼 실제 후보 카메라",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "1"
    });
    await runSelector(page, lowerAuthenticFixture);
    await expect(page.getByTestId("selection-reason")).toContainText(
      "더 낮은 실제 후보"
    );
    await expect(page.getByTestId("koreanet-badge")).toHaveCount(0);
    await expect(page.getByTestId("selected-supplier")).toHaveText("실제 경쟁사");
    await expect(page.getByTestId("export-workbook")).toBeEnabled();
    await confirmExport(page);

    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await readFile(output));
    const sources = workbook.getWorksheet("출처");
    const rows = sources?.getRows(4, (sources?.rowCount ?? 3) - 3) ?? [];
    const selectionRow = rows.find(
      (row) => row.getCell("B").value === "koreanet_selection"
    );
    expect(selectionRow?.getCell("AC").value).toBe(selectedDto);
    expect(selectionRow?.getCell("AA").value).toBe("광주 소재 확인");
    expect(selectionRow?.getCell("AB").value).toBe("전남 서비스 가능 확인");
    await page.screenshot({
      path: path.join(evidenceDirectory, "task-14-koreanet-workflow.png"),
      fullPage: true
    });
  } finally {
    await application.close();
    await cleanupTrustedFixtureApp();
  }
});
