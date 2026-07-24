import { randomUUID } from "node:crypto";
import { rename, rm, writeFile } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import ExcelJS from "exceljs";
import { loadOfficialRepository } from "../official/repository.js";
import { calculateNativeWorkbook } from "./calculation.js";
import { addEstimateSheets } from "./estimate-sheets.js";
import {
  NATIVE_WORKBOOK_CAPACITY,
  NativeWorkbookError,
  parseNativeWorkbookInput
} from "./input.js";
import { addSourceSheets } from "./source-sheets.js";

export {
  NATIVE_WORKBOOK_CAPACITY,
  NativeWorkbookError
} from "./input.js";

export const NATIVE_WORKBOOK_SHEETS = [
  "설정",
  "품목",
  "단가",
  "요약",
  "공식단가",
  "출처"
] as const;

const WORKBOOK_DATE = new Date("2026-01-01T00:00:00.000Z");

export async function createNativeWorkbook(input: unknown): Promise<ArrayBuffer> {
  const parsed = parseNativeWorkbookInput(input);
  const repository = await loadOfficialRepository();
  const calculation = calculateNativeWorkbook(parsed);
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Electron Estimator";
  workbook.lastModifiedBy = "Electron Estimator";
  workbook.created = WORKBOOK_DATE;
  workbook.modified = WORKBOOK_DATE;
  workbook.title = "2026 CCTV/LAN/FIBER 내부검토";
  workbook.subject = "법적 인증이 아닌 출처 추적형 내부검토 workbook";
  workbook.company = "";
  workbook.calcProperties.fullCalcOnLoad = true;
  workbook.views = [{
    x: 0,
    y: 0,
    width: 16_000,
    height: 9_000,
    firstSheet: 0,
    activeTab: 0,
    visibility: "visible"
  }];

  addEstimateSheets(workbook, parsed, calculation, repository);
  addSourceSheets(workbook, parsed, calculation, repository);

  return workbook.xlsx.writeBuffer();
}

export async function writeNativeWorkbook(
  input: unknown,
  destinationPath: string
): Promise<void> {
  const bytes = await createNativeWorkbook(input);
  const temporaryPath = resolve(
    dirname(destinationPath),
    `.${basename(destinationPath)}.native-${randomUUID()}.tmp`
  );
  try {
    await writeFile(temporaryPath, Buffer.from(bytes), { flag: "wx" });
    await rename(temporaryPath, destinationPath);
  } catch (error) {
    await rm(temporaryPath, { force: true });
    throw error;
  }
}
