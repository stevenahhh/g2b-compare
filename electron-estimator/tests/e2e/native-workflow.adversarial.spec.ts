import { expect, test } from "@playwright/test";
import { access } from "node:fs/promises";
import {
  addBlankRow,
  cleanupTrustedFixtureApp,
  fillProject,
  fillUserQuote,
  launchApp,
  launchTrustedFixtureApp,
  noComparableFixture,
  runSelector,
  selectedKoreaNetFixture,
  useSavePath
} from "./native-workflow.helpers.js";

test("Given an export confirmation When it is cancelled Then focus returns and no file is written", async () => {
  const output = test.info().outputPath("cancelled.xlsx");
  const { application, page } = await launchApp();
  await useSavePath(application, output);
  try {
    await fillProject(page);
    await addBlankRow(page, "LAN", {
      itemName: "취소 확인",
      specification: "CAT.6",
      unit: "m",
      quantity: "1"
    });
    await fillUserQuote(page, "1000");
    const trigger = page.getByTestId("export-workbook");
    await trigger.click();
    await page.getByTestId("cancel-export").click();
    await expect(trigger).toBeFocused();
    await expect(access(output)).rejects.toThrow();
  } finally {
    await application.close();
  }
});

test("Given formula-like text and a stale selector When edited through IME Then unsafe export is blocked until reselection", async () => {
  const { application, page } = await launchTrustedFixtureApp();
  try {
    await fillProject(page);
    await page.getByTestId("project-name").fill('=HYPERLINK("https://invalid.test")');
    const row = await addBlankRow(page, "CCTV", {
      itemName: "+SUM(1,1)",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "1"
    });
    await runSelector(page, selectedKoreaNetFixture);
    const specification = row.locator('[data-field="specification"]');
    await specification.evaluate((input) => {
      input.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
      input.value = "변경 중";
      input.dispatchEvent(new InputEvent("input", { bubbles: true, data: "중" }));
      input.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true }));
    });
    await expect(page.getByTestId("validation-errors")).toContainText(
      "오류 STALE_SELECTOR: 행이 변경되어 Task8 선택을 다시 실행해야 함."
    );
    await expect(page.getByTestId("export-workbook")).toBeDisabled();
  } finally {
    await application.close();
    await cleanupTrustedFixtureApp();
  }
});

test("Given forged self-consistent candidate hashes When production selection runs Then no automatic KoreaNet badge is earned", async () => {
  const { application, page } = await launchApp();
  try {
    await fillProject(page);
    await addBlankRow(page, "CCTV", {
      itemName: "위조 후보 차단",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "1"
    });
    const forged = await page.evaluate(
      async ({ comparisonGroup, candidates }) =>
        window.estimator.readSeed({
          kind: "native_select",
          requestedItemKey: comparisonGroup,
          specification: "CCTV 4MP",
          unit: "EA",
          candidates
        } as never),
      selectedKoreaNetFixture
    );
    expect(forged).toMatchObject({
      ok: false,
      error: { code: "IPC_PAYLOAD_REJECTED" }
    });
    await expect(page.getByTestId("candidate-json")).toHaveCount(0);
    await runSelector(page, selectedKoreaNetFixture);
    await expect(page.getByTestId("koreanet-badge")).toHaveCount(0);
    await expect(page.getByTestId("export-result")).toContainText(
      "KOREANET_NOT_AVAILABLE"
    );
  } finally {
    await application.close();
  }
});

test("Given no comparable candidate When selection finishes Then no sourced row is auto-applied", async () => {
  const { application, page } = await launchTrustedFixtureApp();
  try {
    await fillProject(page);
    await addBlankRow(page, "CCTV", {
      itemName: "No comparable candidate",
      specification: "CCTV 4MP",
      unit: "EA",
      quantity: "1"
    });
    await runSelector(page, noComparableFixture);

    await expect(page.getByTestId("export-result")).toContainText(
      "NO_COMPARABLE_CANDIDATE"
    );
    await expect(page.getByTestId("selector-dto")).toHaveCount(0);
    await expect(
      page.locator('[data-provenance-field="제품 ID"]')
    ).toHaveCount(0);
    await expect(
      page.locator('[data-provenance-field="Source URL"]')
    ).toHaveCount(0);
    await expect(page.locator("[data-evidence-field]")).toHaveCount(0);
    await expect(page.getByTestId("validation-errors")).toContainText(
      "SOURCE_REQUIRED"
    );
    await expect(page.getByTestId("export-workbook")).toBeDisabled();
  } finally {
    await application.close();
    await cleanupTrustedFixtureApp();
  }
});
