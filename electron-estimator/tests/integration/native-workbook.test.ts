import { readFile, writeFile } from "node:fs/promises";
import Decimal from "decimal.js";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { expect, test } from "vitest";
import {
  quoteSourceIdentity,
  QuoteSourceSchema
} from "../../src/domain/provenance.js";
import {
  createNativeWorkbook,
  NATIVE_WORKBOOK_CAPACITY,
  NATIVE_WORKBOOK_SHEETS
} from "../../src/native/workbook.js";
import { mixedNativeInput } from "./native-workbook-fixtures.js";

const EXPECTED_SHEETS = ["설정", "품목", "단가", "요약", "공식단가", "출처"] as const;

test("Given a mixed CCTV LAN FIBER project When a native workbook is created Then formulas caches sources and six sheets are exact", async () => {
  // Given
  const input = await mixedNativeInput();
  const mixedQuoteInput = {
    ...input,
    lines: input.lines.map((entry, index) =>
      index === 2
        ? {
            ...entry,
            line: {
              ...entry.line,
              cost: {
                kind: "three_company_min",
                quotes: [
                  {
                    slot: "A",
                    provenance: {
                      ...input.lines[0].line.cost.provenance,
                      observationId: "mixed-direct-a",
                      productId: "11111111",
                      specification: "12CORE",
                      unitPriceWon: "300"
                    }
                  },
                  {
                    slot: "B",
                    provenance: {
                      ...input.lines[1].line.cost.provenance,
                      quoteId: "mixed-user-b",
                      specification: "12CORE",
                      unitPriceWon: "400"
                    }
                  },
                  {
                    slot: "C",
                    provenance: {
                      ...input.lines[0].line.cost.provenance,
                      observationId: "mixed-direct-c",
                      productId: "22222222",
                      specification: "12CORE",
                      unitPriceWon: "600"
                    }
                  }
                ]
              }
            }
          }
        : entry
    )
  };
  const mixedQuotes = mixedQuoteInput.lines[2]?.line.cost;
  if (mixedQuotes?.kind !== "three_company_min") {
    expect.fail("Mixed three-company fixture is missing");
  }
  expect(mixedQuotes.quotes.map((quote) => ({
    slot: quote.slot,
    ...quoteSourceIdentity(QuoteSourceSchema.parse(quote.provenance))
  }))).toEqual([
    { slot: "A", quoteId: "mixed-direct-a", unitPriceWon: new Decimal("300") },
    { slot: "B", quoteId: "mixed-user-b", unitPriceWon: new Decimal("400") },
    { slot: "C", quoteId: "mixed-direct-c", unitPriceWon: new Decimal("600") }
  ]);

  // When
  const bytes = await createNativeWorkbook(mixedQuoteInput);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(bytes);

  // Then
  expect(NATIVE_WORKBOOK_SHEETS).toEqual(EXPECTED_SHEETS);
  expect(NATIVE_WORKBOOK_CAPACITY).toBe(200);
  expect(workbook.worksheets.map((sheet) => sheet.name)).toEqual(EXPECTED_SHEETS);

  const settings = workbook.getWorksheet("설정");
  expect(settings?.getCell("B6").value).toBe(0.0054);
  expect(settings?.getCell("A10").value).toContain("내부 비상업 검토용");
  expect(settings?.getCell("A10").value).toContain("법적 인증 아님");
  expect(settings?.getCell("A10").value).toContain("최신성 보장 없음");
  expect(settings?.getCell("A11").value).toContain("코드 서명되지 않은 시험 빌드");

  const prices = workbook.getWorksheet("단가");
  expect(prices?.getCell("H7").value).toEqual({
    formula: expect.stringContaining("MATCH(MIN("),
    result: "A"
  });
  expect(prices?.getCell("I7").value).toEqual({
    formula: expect.stringContaining("INDEX("),
    result: 300
  });

  const items = workbook.getWorksheet("품목");
  const marketEntry = input.lines[3];
  const standardEntry = input.lines[4];
  if (
    marketEntry?.line.cost.kind !== "market_price" ||
    standardEntry?.line.cost.kind !== "standard_quantity"
  ) {
    expect.fail("Official oracle fixtures are missing");
  }
  const marketAmount = Number(marketEntry.line.cost.provenance.unitPriceWon);
  const standardAmount = standardEntry.line.cost.provenance.coefficients.reduce(
    (total, coefficient) =>
      total + Number(coefficient.coefficient) * Number(coefficient.dailyWageWon),
    0
  );
  const expectedSubtotal = 2000 + 6000 + 300 + marketAmount + standardAmount;
  const expectedFee = new Decimal(expectedSubtotal).times("0.0054").toNumber();
  const expectedRounded = Math.ceil((expectedSubtotal + expectedFee) / 1000) * 1000;
  expect(items?.getCell("H5").value).toEqual({
    formula: expect.stringContaining("'단가'!"),
    result: 2000
  });
  expect(items?.getCell("H7").value).toEqual({
    formula: expect.stringContaining("'단가'!"),
    result: 300
  });
  expect(items?.getCell("H8").value).toEqual({
    formula: expect.stringContaining("'단가'!"),
    result: marketAmount
  });
  expect(items?.getCell("H204").result).toBe(0);

  const summary = workbook.getWorksheet("요약");
  expect(summary?.getCell("E5").value).toEqual({
    formula: "SUM(B5:B204)",
    result: expectedSubtotal
  });
  expect(summary?.getCell("E6").value).toEqual({
    formula: "E5*'설정'!B6",
    result: expectedFee
  });
  expect(summary?.getCell("E9").value).toEqual({
    formula: "ROUNDUP(E7/'설정'!B7,0)*'설정'!B7",
    result: expectedRounded
  });
  expect([12, 13, 14].map((row) => summary?.getCell(`E${row}`).result)).toEqual([
    2000,
    6000 + marketAmount,
    300 + standardAmount
  ]);
  expect(summary?.getCell("B204").result).toBe(0);

  const official = workbook.getWorksheet("공식단가");
  const officialKinds = official
    ?.getColumn("A")
    .values.slice(3)
    .filter((value) => typeof value === "string");
  expect(officialKinds?.filter((value) => value === "market_price")).toHaveLength(64);
  expect(
    officialKinds?.filter((value) => value === "standard_productivity")
  ).toHaveLength(23);
  expect(officialKinds?.filter((value) => value === "wage_rate")).toHaveLength(10);
  const officialRows = official?.getRows(4, 97) ?? [];
  expect(
    ["CCTV", "LAN", "FIBER"].map(
      (field) =>
        officialRows.filter(
          (row) =>
            row.getCell("A").value === "market_price" &&
            row.getCell("B").value === field
        ).length
    )
  ).toEqual([22, 36, 6]);
  const excluded = officialRows.filter((row) => row.getCell("H").value === "excluded");
  expect(excluded).toHaveLength(24);
  expect(excluded.every((row) => row.getCell("J").result === 0)).toBe(true);
  expect(
    officialRows.every(
      (row) =>
        String(row.getCell("L").value).length > 0 &&
        String(row.getCell("M").value).startsWith("https://") &&
        String(row.getCell("N").value).length > 0 &&
        String(row.getCell("O").value).length > 0 &&
        /^[0-9a-f]{64}$/u.test(String(row.getCell("P").value))
    )
  ).toBe(true);

  const sources = workbook.getWorksheet("출처");
  const sourceRows = sources?.getRows(4, sources.rowCount - 3) ?? [];
  const mixedQuoteRows = sourceRows.filter((row) => row.getCell("A").value === "fiber-1");
  expect(mixedQuoteRows.map((row) => [
    row.getCell("C").value,
    row.getCell("F").value,
    row.getCell("W").value
  ])).toEqual([
    ["mixed-direct-a", 300, true],
    ["mixed-user-b", 400, false],
    ["mixed-direct-c", 600, false]
  ]);
  const directRow = sourceRows.find((row) => row.getCell("B").value === "direct");
  const directValues = ["D", "E", "F", "G", "H", "I", "J", "K", "L"]
    .map((column) => directRow?.getCell(column).value);
  expect(directValues).toEqual([
    "12345678", "KoreaNet", 1000, "EA", "CCTV 4MP",
    "https://example.test/products/12345678", "getProductInfo",
    "2026-07-23T10:00:00+09:00", "a".repeat(64)
  ]);
  const koreaNetRow = sourceRows.find(
    (row) => row.getCell("B").value === "koreanet_selection"
  );
  expect(koreaNetRow?.getCell("D").value).toBe("12345678");
  expect(koreaNetRow?.getCell("X").value).toBe("KOREANET_TIED_LOWEST");
  expect(koreaNetRow?.getCell("AA").value).toBe("광주 소재 확인");
  expect(koreaNetRow?.getCell("AB").value).toBe("전남 서비스 가능 확인");
  expect(JSON.parse(String(koreaNetRow?.getCell("AC").value))).toEqual(
    input.koreaNetSelections[0].result
  );
  const userQuoteRow = sourceRows.find((row) => row.getCell("C").value === "user-lan");
  expect(userQuoteRow?.getCell("I").value).toBeNull();

  const evidencePath = process.env["NATIVE_WORKBOOK_EVIDENCE_PATH"];
  if (evidencePath !== undefined) {
    await writeFile(evidencePath, Buffer.from(bytes));
  }
});

test("Given formula-like user text When the workbook is generated Then it remains literal shared text", async () => {
  // Given
  const input = await mixedNativeInput();
  const unsafe = {
    ...input,
    projectName: "=HYPERLINK(\"https://invalid.test\")",
    koreaNetSelections: [],
    lines: input.lines.map((entry, index) =>
      index === 0
        ? {
            ...entry,
            line: {
              ...entry.line,
              itemName: "+SUM(1,1)",
              specification: "@DDE",
              cost:
                entry.line.cost.kind === "direct"
                  ? {
                      ...entry.line.cost,
                      provenance: {
                        ...entry.line.cost.provenance,
                        specification: "@DDE"
                      }
                    }
                  : entry.line.cost
            }
          }
        : entry
    )
  };

  // When
  const bytes = await createNativeWorkbook(unsafe);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(bytes);

  // Then
  expect(workbook.getWorksheet("설정")?.getCell("B3").value).toBe(
    "'=HYPERLINK(\"https://invalid.test\")"
  );
  expect(workbook.getWorksheet("품목")?.getCell("C5").value).toBe("'+SUM(1,1)");
  expect(workbook.getWorksheet("품목")?.getCell("D5").value).toBe("'@DDE");
});

test("Given the same semantic input When generated twice Then semantic workbook content is deterministic", async () => {
  // Given
  const input = await mixedNativeInput();

  // When
  const firstBytes = await createNativeWorkbook(input);
  const secondBytes = await createNativeWorkbook(input);
  const first = new ExcelJS.Workbook();
  const second = new ExcelJS.Workbook();
  await first.xlsx.load(firstBytes);
  await second.xlsx.load(secondBytes);

  // Then
  const semantics = (workbook: ExcelJS.Workbook) =>
    workbook.worksheets.map((sheet) => ({
      name: sheet.name,
      rows: sheet
        .getRows(1, sheet.rowCount)
        ?.map((row) => row.values)
    }));
  expect(semantics(first)).toEqual(semantics(second));
});

test("Given generated XLSX bytes When raw OOXML is inspected Then formulas have caches and no VBA external links or defined names exist", async () => {
  // Given
  const bytes = await createNativeWorkbook(await mixedNativeInput());

  // When
  const zip = await JSZip.loadAsync(bytes);
  const members = Object.keys(zip.files).toSorted();
  const workbookXml = await zip.file("xl/workbook.xml")?.async("string");
  const itemXml = await zip.file("xl/worksheets/sheet2.xml")?.async("string");
  const worksheetXml = (
    await Promise.all(
      members
        .filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/u.test(name))
        .map(async (name) => zip.file(name)?.async("string"))
    )
  ).join("\n");

  // Then
  expect(workbookXml).toBeDefined();
  expect(workbookXml).toContain('fullCalcOnLoad="1"');
  const sheetPositions = EXPECTED_SHEETS
    .map((name) => workbookXml?.indexOf(`name="${name}"`) ?? -1);
  expect(sheetPositions.every((position) => position >= 0)).toBe(true);
  expect(sheetPositions).toEqual(sheetPositions.toSorted((left, right) => left - right));
  expect(itemXml).toMatch(
    /<f>[^<]*(?:'|&apos;)단가(?:'|&apos;)![^<]*<\/f><v>\d+<\/v>/u
  );
  expect(workbookXml).not.toContain("<definedNames");
  expect(worksheetXml).not.toMatch(/#REF!|#VALUE!|#NAME\?|#DIV\/0!/u);
  expect(members.some((name) => /vbaProject|externalLinks|calcChain/iu.test(name))).toBe(
    false
  );
  const relationships = await Promise.all(
    members
      .filter((name) => name.endsWith(".rels"))
      .map(async (name) => zip.file(name)?.async("string"))
  );
  expect(relationships.some((xml) => xml?.includes('TargetMode="External"'))).toBe(
    false
  );
});

test("Given a saved evidence workbook When reloaded from disk Then the native semantic contract survives", async () => {
  const evidencePath = process.env["NATIVE_WORKBOOK_EVIDENCE_PATH"];
  if (evidencePath === undefined) {
    return;
  }

  const workbook = new ExcelJS.Workbook();
  const diskBytes = await readFile(evidencePath);
  await workbook.xlsx.load(Uint8Array.from(diskBytes).buffer);

  expect(workbook.worksheets.map((sheet) => sheet.name)).toEqual(EXPECTED_SHEETS);
  expect(workbook.getWorksheet("요약")?.getCell("E9").result).toEqual(
    expect.any(Number)
  );
});
