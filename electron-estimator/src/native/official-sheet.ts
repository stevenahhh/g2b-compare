import type ExcelJS from "exceljs";
import type { OfficialRepository } from "../official/repository.js";
import { addTitle, finalizeTable, setWidths, styleHeader } from "./format.js";
import { excelSafeText } from "./input.js";

const HEADERS = [
  "kind", "분야", "행 식별자", "명칭/작업/직종", "규격/계수", "단위",
  "공식 금액", "재료 포함", "pricing_method", "합계 기여", "적용/제외 사유",
  "source_id", "source_url", "effective_from", "license_id", "PDF SHA-256",
  "PDF page", "dataset_version", "composite_sha256"
] as const;

export function addOfficialSheet(
  workbook: ExcelJS.Workbook,
  repository: OfficialRepository
): void {
  const sheet = workbook.addWorksheet("공식단가");
  addTitle(sheet, "2026 공식단가 64/23/10", HEADERS.length);
  styleHeader(sheet, 3, HEADERS);
  let rowNumber = 4;
  repository.marketPrices.forEach((row) => {
    const included = row.material_included;
    const output = sheet.getRow(rowNumber);
    output.values = [
      row.kind,
      normalizedField(row.category),
      row.work_code,
      excelSafeText(row.name),
      excelSafeText(row.specification),
      excelSafeText(row.unit),
      row.unit_price_krw,
      included ? "included" : "excluded",
      included ? "market_price" : "excluded_reference",
      null,
      included
        ? repository.marketBreakdown.reasonByState.included
        : repository.marketBreakdown.reasonByState.excluded,
      row.source_id,
      row.source_url,
      row.effective_from,
      row.license_id,
      row.source_pdf_sha256,
      String(row.source_pdf_page),
      repository.revision.datasetVersion,
      repository.revision.compositeSha256
    ];
    output.getCell(10).value = {
      formula: `IF(H${rowNumber}="included",G${rowNumber},0)`,
      result: included ? row.unit_price_krw : 0
    };
    rowNumber += 1;
  });
  repository.productivity.forEach((row) => {
    sheet.addRow([
      row.kind,
      normalizedField(row.category),
      `${row.standard_item}|${row.task}|${row.specification}|${row.unit}`,
      excelSafeText(row.task),
      excelSafeText(JSON.stringify(row.coefficients_by_job_code)),
      excelSafeText(row.unit),
      null,
      "reference",
      "standard_quantity",
      0,
      "표준품셈 계수는 임금과 결합할 때만 금액을 계산함.",
      row.source_id,
      row.source_url,
      row.effective_from,
      row.license_id,
      row.source_pdf_sha256,
      row.source_pdf_pages.join(","),
      repository.revision.datasetVersion,
      repository.revision.compositeSha256
    ]);
  });
  repository.wages.forEach((row) => {
    sheet.addRow([
      row.kind,
      null,
      row.job_code,
      excelSafeText(row.job_name),
      null,
      "일",
      row.daily_wage_krw,
      "reference",
      "standard_quantity_wage",
      0,
      "전국 직종별 일임금 참고값임.",
      row.source_id,
      row.source_url,
      row.effective_from,
      row.license_id,
      row.source_pdf_sha256,
      row.source_pdf_pages.join(","),
      repository.revision.datasetVersion,
      repository.revision.compositeSha256
    ]);
  });
  sheet.getColumn("G").numFmt = "#,##0";
  sheet.getColumn("J").numFmt = "#,##0";
  setWidths(sheet, [24, 10, 42, 30, 42, 10, 16, 14, 24, 16, 56, 30, 44, 14, 24, 68, 14, 34, 68]);
  finalizeTable(sheet, 3, sheet.rowCount, HEADERS.length);
}

function normalizedField(value: string): "CCTV" | "LAN" | "FIBER" {
  return value === "CCTV" || value === "LAN" ? value : "FIBER";
}

