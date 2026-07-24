import type ExcelJS from "exceljs";
import type { EstimateLine } from "../domain/estimate.js";
import type { Provenance, QuoteSource } from "../domain/provenance.js";
import type { OfficialRepository } from "../official/repository.js";
import type { NativeCalculation } from "./calculation.js";
import { addTitle, finalizeTable, setWidths, styleHeader } from "./format.js";
import {
  excelSafeText,
  type NativeSelection,
  type NativeWorkbookInput
} from "./input.js";
import { addOfficialSheet } from "./official-sheet.js";
import { officialDocument } from "./official-source-metadata.js";

const SOURCE_HEADERS = [
  "line_id", "kind", "observation_or_quote_id", "product_id", "supplier",
  "unit_price_won", "unit", "specification", "source_url", "api_operation",
  "observed_at", "source_payload_sha256", "quote_date", "document_sha256",
  "source_id", "source_title", "source_pdf_sha256", "source_pdf_pages",
  "effective_from", "effective_to", "license_id", "verification_status",
  "selected", "selection_reason", "lowest_unit_price_won",
  "compared_observation_ids", "supplier_location_evidence",
  "service_area_evidence", "selector_result_json"
] as const;

export function addSourceSheets(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation,
  repository: OfficialRepository
): void {
  addOfficialSheet(workbook, repository);
  addSourceSheet(workbook, input, calculation);
}

function addSourceSheet(
  workbook: ExcelJS.Workbook,
  input: NativeWorkbookInput,
  calculation: NativeCalculation
): void {
  const sheet = workbook.addWorksheet("출처");
  addTitle(sheet, "가격·공식·KoreaNet 출처", SOURCE_HEADERS.length);
  styleHeader(sheet, 3, SOURCE_HEADERS);
  input.lines.forEach((entry, index) => {
    addLineSources(
      sheet,
      entry.line,
      calculation.lines[index]?.selectedSlot ?? null
    );
  });
  input.koreaNetSelections.forEach((selection) => {
    sheet.addRow(selectionRow(selection));
  });
  sheet.getColumn("F").numFmt = "#,##0";
  setWidths(sheet, [
    18, 26, 28, 14, 26, 14, 10, 34, 44, 24, 26, 68, 14, 68, 30, 48, 68,
    18, 14, 14, 30, 28, 10, 28, 14, 42, 38, 38, 90
  ]);
  finalizeTable(sheet, 3, Math.max(sheet.rowCount, 4), SOURCE_HEADERS.length);
}

function addLineSources(
  sheet: ExcelJS.Worksheet,
  line: EstimateLine,
  selectedSlot: "A" | "B" | "C" | "공식" | "직접" | null
): void {
  switch (line.cost.kind) {
    case "direct":
      sheet.addRow(quoteRow(line.id, line.cost.provenance, selectedSlot === "직접"));
      break;
    case "three_company_min":
      line.cost.quotes.forEach((quote) => {
        sheet.addRow(
          quoteRow(line.id, quote.provenance, selectedSlot === quote.slot)
        );
      });
      break;
    case "market_price":
      sheet.addRow(officialRow(line.id, line.cost.provenance));
      break;
    case "standard_quantity":
      sheet.addRow(officialRow(line.id, line.cost.provenance));
      line.cost.provenance.coefficients.forEach((coefficient) => {
        sheet.addRow(
          wageRow(
            line.id,
            coefficient.jobCode,
            coefficient.dailyWageWon.toNumber(),
            coefficient.wageSource
          )
        );
      });
      break;
    default:
      assertNever(line.cost);
  }
}

function quoteRow(
  lineId: string,
  source: QuoteSource,
  selected: boolean
): readonly (string | number | boolean | null)[] {
  switch (source.kind) {
    case "direct":
      return [
        lineId, source.kind, excelSafeText(source.observationId), source.productId,
        excelSafeText(source.supplierName), source.unitPriceWon.toNumber(),
        excelSafeText(source.unit), excelSafeText(source.specification),
        source.sourceUrl, excelSafeText(source.apiOperation), source.observedAt,
        source.sourcePayloadSha256, null, null, null, null, null, null, null,
        null, null, null, selected, null, null, null, null, null, null
      ];
    case "user_quote":
      return [
        lineId, "user_entered_price", excelSafeText(source.quoteId), null,
        excelSafeText(source.supplierName), source.unitPriceWon.toNumber(),
        excelSafeText(source.unit), excelSafeText(source.specification),
        null, null, null, null, source.quoteDate, source.documentSha256, null,
        null, null, null, null, null, null, "미검증", selected, null, null, null,
        null, null, null
      ];
    default:
      return assertNever(source);
  }
}

function officialRow(
  lineId: string,
  source: Extract<Provenance, { readonly kind: "market_price" | "standard_quantity" }>
): readonly (string | number | boolean | null)[] {
  const document = officialDocument(source.sourceId);
  return [
    lineId,
    source.kind,
    source.kind === "market_price" ? source.workCode : source.standardItem,
    null,
    null,
    source.kind === "market_price" ? source.unitPriceWon.toNumber() : null,
    excelSafeText(source.unit),
    excelSafeText(source.specification),
    source.sourceUrl,
    null,
    null,
    null,
    null,
    null,
    source.sourceId,
    document.title,
    source.sourcePdfSha256,
    source.sourcePdfPages.join(","),
    source.effectiveFrom,
    null,
    document.licenseId,
    "VERIFIED_OFFICIAL_PDF",
    true,
    null,
    null,
    null,
    null,
    null,
    null
  ];
}

function wageRow(
  lineId: string,
  jobCode: string,
  dailyWageWon: number,
  source: Extract<
    Provenance,
    { readonly kind: "standard_quantity" }
  >["coefficients"][number]["wageSource"]
): readonly (string | number | boolean | null)[] {
  const document = officialDocument(source.sourceId);
  return [
    lineId, "wage_source", jobCode, null, null, dailyWageWon, "일", null,
    source.sourceUrl, null, null, null, null, null, source.sourceId,
    document.title, source.sourcePdfSha256, source.sourcePdfPages.join(","),
    source.effectiveFrom, null, document.licenseId, "VERIFIED_OFFICIAL_PDF",
    true, null, null, null, null, null, null
  ];
}

function selectionRow(
  selection: NativeSelection
): readonly (string | number | boolean | null)[] {
  if (selection.result.kind === "not_selected") {
    return [
      selection.lineId, "koreanet_selection", null, null, null, null, null, null,
      null, null, null, null, null, null, null, null, null, null, null, null,
      null, null, false, selection.result.reason, selection.result.lowestUnitPriceWon,
      excelSafeText(
        selection.result.comparableCandidates
          .map((item) => item.observation_id)
          .join(",")
      ),
      null, null, JSON.stringify(selection.result)
    ];
  }
  const selected = selection.result.selected;
  return [
    selection.lineId,
    "koreanet_selection",
    excelSafeText(selected.observation_id),
    selected.product_id,
    excelSafeText(selected.supplier_name),
    selected.unit_price_won,
    excelSafeText(selected.unit),
    excelSafeText(selected.spec_snapshot),
    selected.source_url,
    excelSafeText(selected.api_operation),
    selected.observed_at,
    selected.source_payload_sha256,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    true,
    selection.result.reason,
    selection.result.lowestUnitPriceWon,
    excelSafeText(
      selection.result.comparableCandidates
        .map((item) => item.observation_id)
        .join(",")
    ),
    selected.supplier_location_evidence === undefined
      ? null
      : excelSafeText(selected.supplier_location_evidence.statement),
    selected.service_area_evidence === undefined
      ? null
      : excelSafeText(selected.service_area_evidence.statement),
    JSON.stringify(selection.result)
  ];
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected source kind: ${String(value)}`);
}
