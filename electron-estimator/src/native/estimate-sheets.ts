import type ExcelJS from "exceljs";
import type Decimal from "decimal.js";
import type { OfficialRepository } from "../official/repository.js";
import type {
  NativeCalculation,
  NativeLineCalculation
} from "./calculation.js";
import {
  REFERENCE_FEE_RATE,
  ROUNDING_INCREMENT_WON
} from "./calculation.js";
import { addTitle, finalizeTable, setWidths, styleHeader } from "./format.js";
import {
  excelSafeText,
  NATIVE_WORKBOOK_CAPACITY,
  type NativeWorkbookInput
} from "./input.js";

const FIRST_SLOT_ROW = 5;
const LAST_SLOT_ROW = FIRST_SLOT_ROW + NATIVE_WORKBOOK_CAPACITY - 1;
const NOTICE =
  "내부 비상업 검토용 · 법적 인증 아님 · 최신성 보장 없음";
const UNSIGNED_NOTICE =
  "주의: 코드 서명되지 않은 시험 빌드임. 운영체제가 배포자 신원을 검증하지 못함.";

export function addEstimateSheets(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation,
  repository: OfficialRepository
): void {
  addSettingsSheet(workbook, input, repository);
  addItemSheet(workbook, input, calculation);
  addPriceSheet(workbook, input, calculation);
  addSummarySheet(workbook, input, calculation);
}

function addSettingsSheet(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  repository: OfficialRepository
): void {
  const sheet = workbook.addWorksheet("설정");
  addTitle(sheet, "2026 CCTV/LAN/FIBER 내부검토 설정", 4);
  const values: readonly (readonly [string, string | number])[] = [
    ["프로젝트 ID", input.projectId],
    ["프로젝트명", excelSafeText(input.projectName)],
    ["작성 기준일", input.preparedOn],
    ["공식 데이터 버전", repository.revision.datasetVersion],
    ["참고 조달수수료율", REFERENCE_FEE_RATE.toNumber()],
    ["참고 반올림 단위(원)", ROUNDING_INCREMENT_WON.toNumber()],
    ["공식 데이터 SHA-256", repository.revision.compositeSha256]
  ];
  values.forEach(([label, value], index) => {
    const row = index + 2;
    sheet.getCell(row, 1).value = label;
    sheet.getCell(row, 2).value = value;
  });
  sheet.getCell("C6").value =
    "확인 필요: 0.54%는 보편적 법정 요율이 아닌 참고 설정임.";
  sheet.mergeCells("A10:D10");
  sheet.getCell("A10").value = NOTICE;
  sheet.mergeCells("A11:D11");
  sheet.getCell("A11").value = UNSIGNED_NOTICE;
  for (const row of [10, 11]) {
    sheet.getCell(row, 1).font = { bold: true, color: { argb: "FFDA1E28" } };
    sheet.getCell(row, 1).alignment = { wrapText: true, vertical: "middle" };
    sheet.getRow(row).height = 30;
  }
  sheet.getColumn("A").font = { bold: true };
  sheet.getColumn("B").numFmt = "0.00%";
  sheet.getCell("B7").numFmt = "#,##0";
  setWidths(sheet, [25, 74, 68, 12]);
  sheet.views = [{ state: "frozen", ySplit: 1 }];
}

function addItemSheet(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation
): void {
  const sheet = workbook.addWorksheet("품목");
  addTitle(sheet, "품목 200행 고정 슬롯", 8);
  styleHeader(sheet, 4, [
    "분야",
    "행 ID",
    "품목명",
    "규격",
    "단위",
    "수량",
    "가격방식",
    "품목금액(원)"
  ]);
  for (let slot = 0; slot < NATIVE_WORKBOOK_CAPACITY; slot += 1) {
    const rowNumber = FIRST_SLOT_ROW + slot;
    const entry = input.lines[slot];
    const result = calculation.lines[slot];
    const row = sheet.getRow(rowNumber);
    row.values = entry === undefined
      ? [null, null, null, null, null, null, null]
      : [
          entry.field,
          entry.line.id,
          excelSafeText(entry.line.itemName),
          excelSafeText(entry.line.specification),
          excelSafeText(entry.line.unit),
          entry.line.quantity.toNumber(),
          entry.line.cost.kind
        ];
    row.getCell(8).value = {
      formula: `IF(B${rowNumber}="",0,F${rowNumber}*'단가'!I${rowNumber})`,
      result: result?.amountWon.toNumber() ?? 0
    };
    row.getCell(6).dataValidation = {
      type: "decimal",
      operator: "greaterThan",
      formulae: [0],
      allowBlank: true,
      showErrorMessage: true,
      errorTitle: "수량 오류",
      error: "수량은 0보다 커야 함."
    };
    row.getCell(8).numFmt = "#,##0";
  }
  setWidths(sheet, [10, 18, 30, 34, 10, 12, 22, 18]);
  finalizeTable(sheet, 4, LAST_SLOT_ROW, 8);
}

function addPriceSheet(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation
): void {
  const sheet = workbook.addWorksheet("단가");
  addTitle(sheet, "단가 200행 고정 슬롯", 9);
  styleHeader(sheet, 4, [
    "행 ID",
    "분야",
    "가격방식",
    "직접/공식",
    "A사",
    "B사",
    "C사",
    "선택",
    "적용단가(원)"
  ]);
  for (let slot = 0; slot < NATIVE_WORKBOOK_CAPACITY; slot += 1) {
    const rowNumber = FIRST_SLOT_ROW + slot;
    const entry = input.lines[slot];
    const result = calculation.lines[slot];
    const quotes = entry?.line.cost.kind === "three_company_min"
      ? entry.line.cost.quotes.map((quote) => quote.provenance.unitPriceWon.toNumber())
      : [];
    const row = sheet.getRow(rowNumber);
    row.values = [
      entry?.line.id ?? null,
      entry?.field ?? null,
      entry?.line.cost.kind ?? null,
      directOrOfficialPrice(result),
      quotes[0] ?? null,
      quotes[1] ?? null,
      quotes[2] ?? null
    ];
    row.getCell(8).value = {
      formula:
        `IF(C${rowNumber}="","",IF(C${rowNumber}="three_company_min",` +
        `INDEX({"A","B","C"},MATCH(MIN(E${rowNumber}:G${rowNumber}),E${rowNumber}:G${rowNumber},0)),` +
        `IF(C${rowNumber}="direct","직접","공식")))`,
      result: result?.selectedSlot ?? ""
    };
    row.getCell(9).value = {
      formula:
        `IF(H${rowNumber}="",0,IF(OR(H${rowNumber}="직접",H${rowNumber}="공식"),` +
        `D${rowNumber},INDEX(E${rowNumber}:G${rowNumber},1,MATCH(H${rowNumber},{"A","B","C"},0))))`,
      result: result?.unitPriceWon.toNumber() ?? 0
    };
    for (let column = 4; column <= 7; column += 1) {
      row.getCell(column).dataValidation = {
        type: "decimal",
        operator: "greaterThan",
        formulae: [0],
        allowBlank: true,
        showErrorMessage: true,
        errorTitle: "단가 오류",
        error: "단가는 0보다 커야 함."
      };
      row.getCell(column).numFmt = "#,##0";
    }
    row.getCell(9).numFmt = "#,##0";
  }
  setWidths(sheet, [18, 10, 22, 16, 14, 14, 14, 12, 18]);
  finalizeTable(sheet, 4, LAST_SLOT_ROW, 9);
}

function addSummarySheet(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation
): void {
  const sheet = workbook.addWorksheet("요약");
  addTitle(sheet, "요약 200행 고정 슬롯", 5);
  styleHeader(sheet, 4, ["분야", "품목금액(원)", "", "집계", "금액(원)"]);
  for (let slot = 0; slot < NATIVE_WORKBOOK_CAPACITY; slot += 1) {
    const rowNumber = FIRST_SLOT_ROW + slot;
    const entry = input.lines[slot];
    const result = calculation.lines[slot];
    sheet.getCell(rowNumber, 1).value = entry?.field ?? null;
    sheet.getCell(rowNumber, 2).value = {
      formula: `IF('품목'!B${rowNumber}="",0,'품목'!H${rowNumber})`,
      result: result?.amountWon.toNumber() ?? 0
    };
    sheet.getCell(rowNumber, 2).numFmt = "#,##0";
  }
  setSummaryValue(sheet, 5, "소계", "SUM(B5:B204)", calculation.subtotalWon);
  setSummaryValue(sheet, 6, "참고 수수료", "E5*'설정'!B6", calculation.referenceFeeWon);
  setSummaryValue(sheet, 7, "반올림 전 합계", "E5+E6", calculation.unroundedTotalWon);
  setSummaryValue(sheet, 8, "반올림 조정", "E9-E7", calculation.roundingAdjustmentWon);
  setSummaryValue(
    sheet,
    9,
    "참고 반올림 합계",
    "ROUNDUP(E7/'설정'!B7,0)*'설정'!B7",
    calculation.roundedTotalWon
  );
  (["CCTV", "LAN", "FIBER"] as const).forEach((field, index) => {
    const row = 12 + index;
    sheet.getCell(row, 4).value = field;
    sheet.getCell(row, 5).value = {
      formula: `SUMIF(A5:A204,D${row},B5:B204)`,
      result: calculation.fieldSubtotals[field].toNumber()
    };
    sheet.getCell(row, 5).numFmt = "#,##0";
  });
  setWidths(sheet, [12, 20, 4, 24, 20]);
  finalizeTable(sheet, 4, LAST_SLOT_ROW, 5);
}

function directOrOfficialPrice(
  result: NativeLineCalculation | undefined
): number | null {
  return result === undefined || ["A", "B", "C"].includes(result.selectedSlot)
    ? null
    : result.unitPriceWon.toNumber();
}

function setSummaryValue(
  sheet: ExcelJS.Worksheet,
  row: number,
  label: string,
  formula: string,
  result: Decimal
): void {
  sheet.getCell(row, 4).value = label;
  sheet.getCell(row, 5).value = { formula, result: result.toNumber() };
  sheet.getCell(row, 5).numFmt = "#,##0.00";
}

