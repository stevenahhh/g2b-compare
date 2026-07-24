import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import { afterAll, beforeAll, expect, test } from "vitest";
import {
  prepareQaWorkbooks
} from "../../scripts/prepare-qa-workbooks.mjs";
import {
  assertScreenshotWithinProfile
} from "../../scripts/artifact-qa.mjs";
import {
  verifyWorkbook
} from "../../scripts/verify-workbook.mjs";

let directory = "";
let receipt: Awaited<ReturnType<typeof prepareQaWorkbooks>>;
const execFileAsync = promisify(execFile);

beforeAll(async () => {
  directory = await mkdtemp(join(tmpdir(), "estimator-workbook-qa-"));
  receipt = await prepareQaWorkbooks(directory);
}, 120_000);

afterAll(async () => {
  await rm(directory, { recursive: true, force: true });
});

test("prepares three verified legacy pairs and one native workbook without changing sources", async () => {
  expect(receipt.status).toBe("pass");
  expect(receipt.legacy).toHaveLength(3);
  expect(receipt.native.status).toBe("pass");
  expect(receipt.legacy.every((entry) =>
    entry.sourceSha256Before === entry.sourceSha256After
  )).toBe(true);
  expect(receipt.legacy.every((entry) =>
    entry.validationStatus === "pass" &&
    entry.outputSha256.length === 64 &&
    entry.reportSha256.length === 64
  )).toBe(true);
  expect(receipt.native.outputSha256).toHaveLength(64);

  const saved = JSON.parse(
    await readFile(join(directory, "task-15-prepare-receipt.json"), "utf8")
  ) as { readonly status: string };
  expect(saved.status).toBe("pass");
});

test("verifies workbook structure and rejects paths under the source dataset", async () => {
  const native = await verifyWorkbook(receipt.native.path);

  expect(native.status).toBe("pass");
  expect(native.sheetNames).toEqual([
    "설정",
    "품목",
    "단가",
    "요약",
    "공식단가",
    "출처"
  ]);
  expect(native.formulaErrors).toEqual([]);

  const source = resolve(
    import.meta.dirname,
    "..",
    "..",
    "..",
    "dataset",
    "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx"
  );
  await expect(verifyWorkbook(source, { rejectSourceDataset: true }))
    .rejects.toThrow("QA_SOURCE_PATH_FORBIDDEN");
});

test("Excel QA refuses a source workbook before launching Excel", async () => {
  const source = resolve(
    import.meta.dirname,
    "..",
    "..",
    "..",
    "dataset",
    "순천 향교 CCTV 구매 설치 - 내역서(관급)(0706수정).xlsx"
  );
  const script = resolve(
    import.meta.dirname,
    "..",
    "..",
    "scripts",
    "excel-qa.ps1"
  );
  const output = resolve(directory, "forbidden-excel-copy");

  await expect(execFileAsync("powershell.exe", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    script,
    "-InputPath",
    source,
    "-OutDir",
    output
  ])).rejects.toMatchObject({
    code: 1,
    stderr: expect.stringContaining("QA_SOURCE_PATH_FORBIDDEN")
  });
});

test("artifact screenshot dimensions are bound to each profile manifest range", () => {
  expect(assertScreenshotWithinProfile("A-output.xlsx", {
    width: 2_314,
    height: 993
  })).toMatchObject({ profile: "A", manifestRange: "B1:R31" });
  expect(assertScreenshotWithinProfile("B-output.xlsx", {
    width: 2_252,
    height: 1_009
  })).toMatchObject({ profile: "B", manifestRange: "A1:W25" });
  expect(assertScreenshotWithinProfile("C-output.xlsx", {
    width: 2_265,
    height: 1_603
  })).toMatchObject({ profile: "C", manifestRange: "A1:W41" });
  expect(assertScreenshotWithinProfile("native-output.xlsx", {
    width: 680,
    height: 4_135
  })).toMatchObject({ profile: "native", manifestRange: "A1:E204" });
  expect(() => assertScreenshotWithinProfile("B-output.xlsx", {
    width: 2_252,
    height: 1_601
  })).toThrow("ARTIFACT_QA_RENDER_DIMENSIONS");
});
