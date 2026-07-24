import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { _electron as electron } from "playwright";

const SOURCE = path.resolve(
  "..",
  "dataset",
  "전남 광양시 아트케이션 관광스테이 확충사업 CCTV 설비 - 내역서(관급)(최종).xlsx"
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

test("legacy profile C and export acknowledgement remain legible at 1440 and 1024", async () => {
  await mkdir(EVIDENCE_ROOT, { recursive: true });
  const application = await electron.launch({ args: ["dist/main/index.js"] });
  const page = await application.firstWindow();
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByTestId("open-legacy-workflow").click();
    await useSourceDialog(application);
    await page.getByTestId("import-legacy").click();
    await expect(page.getByTestId("legacy-workflow")).toHaveAttribute(
      "data-profile",
      "C"
    );
    await expect(page.getByTestId("inherited-warning")).toContainText("U13:U17");
    expect(
      (await page.locator(".legacy-table th").nth(3).boundingBox())?.width
    ).toBeGreaterThan(300);
    await page.screenshot({
      path: path.join(EVIDENCE_ROOT, "task-16-legacy-1440.png"),
      fullPage: true
    });

    await page.getByTestId("export-legacy").click();
    await expect(page.getByTestId("legacy-export-confirmation")).toBeVisible();
    await expect(page.getByTestId("legacy-export-ack")).toBeFocused();
    await expect(page.getByTestId("legacy-export-ack")).toHaveCSS(
      "outline-width",
      "3px"
    );
    await expect(page.getByTestId("legacy-modal-legal")).toContainText(
      "법적 인증 아님"
    );
    await expect(page.getByTestId("legacy-modal-unsigned")).toContainText(
      "코드 서명되지 않은 시험 빌드"
    );
    await expect(page.getByTestId("legacy-modal-inherited")).toContainText(
      "U13:U17"
    );
    await expect(page.getByTestId("legacy-modal-inherited")).toContainText(
      "외부 링크"
    );
    await expect(page.getByTestId("legacy-modal-official-date")).toContainText(
      "공식자료 기준일: 미적용"
    );
    await page.screenshot({
      path: path.join(EVIDENCE_ROOT, "task-16-legacy-confirmation-1440.png"),
      fullPage: true
    });
    await page.keyboard.press("Escape");

    await page.setViewportSize({ width: 1024, height: 768 });
    expect((await page.getByTestId("left-rail").boundingBox())?.width).toBe(56);
    await expect(page.getByTestId("legacy-inspector")).toBeHidden();
    expect(
      (await page.locator(".legacy-table th").nth(3).boundingBox())?.width
    ).toBeGreaterThan(500);
    for (const testId of ["legal-notice", "unsigned-notice"]) {
      expect(
        await page.getByTestId(testId).evaluate(
          (node) =>
            node.scrollWidth <= node.clientWidth &&
            node.scrollHeight <= node.clientHeight
        )
      ).toBe(true);
    }
    await page.screenshot({
      path: path.join(EVIDENCE_ROOT, "task-16-legacy-1024.png"),
      fullPage: true
    });
  } finally {
    await application.close();
  }
});

async function useSourceDialog(
  application: Awaited<ReturnType<typeof electron.launch>>
): Promise<void> {
  await application.evaluate(
    ({ dialog }, source) => {
      Object.defineProperty(dialog, "showOpenDialog", {
        configurable: true,
        value: async () => ({ canceled: false, filePaths: [source] })
      });
    },
    SOURCE
  );
}
