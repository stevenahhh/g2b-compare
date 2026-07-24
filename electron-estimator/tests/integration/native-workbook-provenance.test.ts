import ExcelJS from "exceljs";
import { expect, test } from "vitest";
import { createNativeWorkbook } from "../../src/native/workbook.js";
import { loadOfficialRepository } from "../../src/official/repository.js";
import { mixedNativeInput } from "./native-workbook-fixtures.js";

type ExpectedOfficialSource = {
  readonly effectiveFrom: string;
  readonly identity: string;
  readonly kind: "market_price" | "standard_quantity" | "wage_source";
  readonly licenseId: string;
  readonly lineId: string;
  readonly sourceId: string;
  readonly sourcePdfPages: string;
  readonly sourcePdfSha256: string;
  readonly sourceTitle: string;
  readonly sourceUrl: string;
};

test("Given applied official price productivity and wage rows When the XLSX is independently reloaded Then exact source metadata is visible", async () => {
  // Given
  const input = await mixedNativeInput();
  const repository = await loadOfficialRepository();

  // When
  const bytes = await createNativeWorkbook(input);
  const reloaded = new ExcelJS.Workbook();
  await reloaded.xlsx.load(bytes);

  // Then
  const sheet = reloaded.getWorksheet("출처");
  if (sheet === undefined) {
    expect.fail("Source sheet is missing");
  }
  const columns = {
    effectiveFrom: findColumn(sheet, "effective_from"),
    effectiveTo: findColumn(sheet, "effective_to"),
    identity: findColumn(sheet, "observation_or_quote_id"),
    kind: findColumn(sheet, "kind"),
    licenseId: findColumn(sheet, "license_id"),
    lineId: findColumn(sheet, "line_id"),
    quoteDate: findColumn(sheet, "quote_date"),
    sourceId: findColumn(sheet, "source_id"),
    sourcePdfPages: findColumn(sheet, "source_pdf_pages"),
    sourcePdfSha256: findColumn(sheet, "source_pdf_sha256"),
    sourceTitle: findColumn(sheet, "source_title"),
    sourceUrl: findColumn(sheet, "source_url"),
    verificationStatus: findColumn(sheet, "verification_status")
  };
  const rows = sheet.getRows(4, Math.max(0, sheet.rowCount - 3)) ?? [];
  const market = repository.marketPrices.find(
    (row) => row.work_code === input.lines[3]?.line.cost.provenance.workCode
  );
  const productivity = repository.productivity.find(
    (row) =>
      row.standard_item ===
      input.lines[4]?.line.cost.provenance.standardItem
  );
  if (market === undefined || productivity === undefined) {
    expect.fail("Applied official fixtures are missing");
  }
  const expected: ExpectedOfficialSource[] = [
    {
      effectiveFrom: market.effective_from,
      identity: market.work_code,
      kind: "market_price",
      licenseId: market.license_id,
      lineId: "lan-official",
      sourceId: market.source_id,
      sourcePdfPages: String(market.source_pdf_page),
      sourcePdfSha256: market.source_pdf_sha256,
      sourceTitle: officialTitle(market.source_id),
      sourceUrl: market.source_url
    },
    {
      effectiveFrom: productivity.effective_from,
      identity: productivity.standard_item,
      kind: "standard_quantity",
      licenseId: productivity.license_id,
      lineId: "fiber-official",
      sourceId: productivity.source_id,
      sourcePdfPages: productivity.source_pdf_pages.join(","),
      sourcePdfSha256: productivity.source_pdf_sha256,
      sourceTitle: officialTitle(productivity.source_id),
      sourceUrl: productivity.source_url
    },
    ...Object.keys(productivity.coefficients_by_job_code).map((jobCode) => {
      const wage = repository.wages.find((row) => row.job_code === jobCode);
      if (wage === undefined) {
        throw new TypeError(`Applied wage ${jobCode} is missing`);
      }
      return {
        effectiveFrom: wage.effective_from,
        identity: wage.job_code,
        kind: "wage_source",
        licenseId: wage.license_id,
        lineId: "fiber-official",
        sourceId: wage.source_id,
        sourcePdfPages: wage.source_pdf_pages.join(","),
        sourcePdfSha256: wage.source_pdf_sha256,
        sourceTitle: officialTitle(wage.source_id),
        sourceUrl: wage.source_url
      } satisfies ExpectedOfficialSource;
    })
  ];
  expected.forEach((source) => {
    const row = rows.find(
      (candidate) =>
        candidate.getCell(columns.lineId).value === source.lineId &&
        candidate.getCell(columns.kind).value === source.kind &&
        candidate.getCell(columns.identity).value === source.identity
    );
    if (row === undefined) {
      expect.fail(`Applied source row ${source.kind}/${source.identity} is missing`);
    }
    expect({
      effectiveFrom: row.getCell(columns.effectiveFrom).value,
      effectiveTo: row.getCell(columns.effectiveTo).value,
      licenseId: row.getCell(columns.licenseId).value,
      sourceId: row.getCell(columns.sourceId).value,
      sourcePdfPages: row.getCell(columns.sourcePdfPages).value,
      sourcePdfSha256: row.getCell(columns.sourcePdfSha256).value,
      sourceTitle: row.getCell(columns.sourceTitle).value,
      sourceUrl: row.getCell(columns.sourceUrl).value,
      verificationStatus: row.getCell(columns.verificationStatus).value
    }).toEqual({
      effectiveFrom: source.effectiveFrom,
      effectiveTo: null,
      licenseId: source.licenseId,
      sourceId: source.sourceId,
      sourcePdfPages: source.sourcePdfPages,
      sourcePdfSha256: source.sourcePdfSha256,
      sourceTitle: source.sourceTitle,
      sourceUrl: source.sourceUrl,
      verificationStatus: "VERIFIED_OFFICIAL_PDF"
    });
    expect(row.getCell(columns.quoteDate).value).toBeNull();
  });
  const userQuote = rows.find(
    (row) => row.getCell(columns.identity).value === "user-lan"
  );
  expect(userQuote?.getCell(columns.quoteDate).value).toBe("2026-07-23");
  expect(userQuote?.getCell(columns.effectiveFrom).value).toBeNull();
});

function findColumn(sheet: ExcelJS.Worksheet, header: string): number {
  for (let column = 1; column <= sheet.columnCount; column += 1) {
    if (sheet.getCell(3, column).value === header) {
      return column;
    }
  }
  throw new TypeError(`Source column ${header} is missing`);
}

function officialTitle(sourceId: string): string {
  switch (sourceId) {
    case "KICI_2026_STANDARD_PRODUCTIVITY":
      return "2026년 적용 정보통신공사 표준품셈";
    case "KICI_2026_H2_MARKET_PRICE":
      return "2026년도 하반기 적용 정보통신공사 표준시장단가";
    case "CAK_2026_H1_WAGE":
      return "2026년 상반기 적용 건설업 임금실태 조사 보고서";
    default:
      throw new TypeError(`Unexpected official source ${sourceId}`);
  }
}
