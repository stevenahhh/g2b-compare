import { mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { afterEach, expect, test } from "vitest";
import {
  createNativeWorkbook,
  NativeWorkbookError,
  writeNativeWorkbook
} from "../../src/native/workbook.js";
import { mixedNativeInput } from "./native-workbook-fixtures.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true })
    )
  );
});

test("Given market and standard quantity fields coexist When generation starts Then it rejects double-counted official method", async () => {
  // Given
  const input = await mixedNativeInput();
  const marketLine = input.lines[3]?.line;
  const standardLine = input.lines[4]?.line;
  if (
    marketLine?.cost.kind !== "market_price" ||
    standardLine?.cost.kind !== "standard_quantity"
  ) {
    expect.fail("Official fixture methods are missing");
  }
  const conflicting = {
    ...input,
    lines: [
      {
        ...input.lines[0],
        line: {
          ...marketLine,
          cost: {
            kind: "market_price",
            provenance: marketLine.cost.provenance,
            rateContext: marketLine.cost.rateContext,
            productivity: standardLine.cost.provenance,
            wages: standardLine.cost.provenance.coefficients
          }
        }
      }
    ]
  };

  // When
  const result = createNativeWorkbook(conflicting);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "PRICING_METHOD_CONFLICT"
  } satisfies Partial<NativeWorkbookError>);
});

test.each([
  ["quantity", { quantity: "0" }],
  [
    "price",
    {
      cost: {
        kind: "direct",
        provenance: {
          kind: "user_quote",
          quoteId: "invalid-price",
          supplierName: "사용자",
          unitPriceWon: "0",
          specification: "CCTV 4MP",
          unit: "EA",
          quoteDate: "2026-07-23",
          documentSha256: "a".repeat(64)
        }
      }
    }
  ],
  ["specification", { specification: "" }]
])(
  "Given invalid %s When generation starts Then no XLSX bytes are returned",
  async (_caseName, change) => {
    // Given
    const input = await mixedNativeInput();
    const first = input.lines[0];
    if (first === undefined) {
      expect.fail("Native fixture line is missing");
    }
    const invalid = {
      ...input,
      lines: [
        {
          ...first,
          line: {
            ...first.line,
            ...change
          }
        }
      ],
      koreaNetSelections: []
    };

    // When
    const result = createNativeWorkbook(invalid);

    // Then
    await expect(result).rejects.toBeInstanceOf(NativeWorkbookError);
  }
);

test("Given an invalid source URL When generation starts Then provenance is rejected", async () => {
  // Given
  const input = await mixedNativeInput();
  const first = input.lines[0];
  if (first?.line.cost.kind !== "direct" || first.line.cost.provenance.kind !== "direct") {
    expect.fail("Direct fixture line is missing");
  }
  const invalid = {
    ...input,
    lines: [
      {
        ...first,
        line: {
          ...first.line,
          cost: {
            ...first.line.cost,
            provenance: {
              ...first.line.cost.provenance,
              sourceUrl: "javascript:alert(1)"
            }
          }
        }
      }
    ],
    koreaNetSelections: []
  };

  // When
  const result = createNativeWorkbook(invalid);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "INVALID_INPUT"
  } satisfies Partial<NativeWorkbookError>);
});

test("Given stale official hashes When generation starts Then provenance is rejected", async () => {
  // Given
  const input = await mixedNativeInput();
  const entry = input.lines[3];
  if (entry?.line.cost.kind !== "market_price") {
    expect.fail("Market fixture line is missing");
  }
  const stale = {
    ...input,
    lines: [
      {
        ...entry,
        line: {
          ...entry.line,
          cost: {
            ...entry.line.cost,
            provenance: {
              ...entry.line.cost.provenance,
              compositeSha256: "0".repeat(64)
            }
          }
        }
      }
    ]
  };

  // When
  const result = createNativeWorkbook(stale);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "STALE_PROVENANCE"
  } satisfies Partial<NativeWorkbookError>);
});

test("Given 201 items When generation starts Then the fixed capacity is enforced", async () => {
  // Given
  const input = await mixedNativeInput();
  const first = input.lines[1];
  if (first === undefined) {
    expect.fail("Native fixture line is missing");
  }
  const overflow = {
    ...input,
    lines: Array.from({ length: 201 }, (_, index) => ({
      ...first,
      line: {
        ...first.line,
        id: `line-${index}`
      }
    })),
    koreaNetSelections: []
  };

  // When
  const result = createNativeWorkbook(overflow);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "NATIVE_CAPACITY_EXCEEDED"
  } satisfies Partial<NativeWorkbookError>);
});

test("Given a rename interruption When writing Then no partial XLSX or temp file remains", async () => {
  // Given
  const directory = resolve(
    process.env["TEMP"] ?? process.cwd(),
    `native-workbook-interrupt-${process.pid}-${Date.now()}`
  );
  temporaryDirectories.push(directory);
  await mkdir(directory, { recursive: true });
  const destination = resolve(directory, "blocked.xlsx");
  await mkdir(destination);

  // When
  const result = writeNativeWorkbook(await mixedNativeInput(), destination);

  // Then
  await expect(result).rejects.toBeDefined();
  expect((await readdir(directory)).toSorted()).toEqual(["blocked.xlsx"]);
});

test("Given an unrelated dirty sibling file When writing succeeds Then the dirty boundary is untouched", async () => {
  // Given
  const directory = resolve(
    process.env["TEMP"] ?? process.cwd(),
    `native-workbook-dirty-${process.pid}-${Date.now()}`
  );
  temporaryDirectories.push(directory);
  await mkdir(directory, { recursive: true });
  const dirty = resolve(directory, "unrelated.txt");
  const destination = resolve(directory, "result.xlsx");
  await writeFile(dirty, "preserve me");

  // When
  await writeNativeWorkbook(await mixedNativeInput(), destination);

  // Then
  expect((await readdir(directory)).toSorted()).toEqual([
    "result.xlsx",
    "unrelated.txt"
  ]);
});

test("Given a misleading cached amount When independently reconciled Then the cache mismatch is observable", async () => {
  // Given
  const bytes = await createNativeWorkbook(await mixedNativeInput());
  const zip = await JSZip.loadAsync(bytes);
  const path = "xl/worksheets/sheet2.xml";
  const itemXml = await zip.file(path)?.async("string");
  if (itemXml === undefined) {
    expect.fail("Item worksheet XML is missing");
  }
  zip.file(
    path,
    itemXml.replace(
      "<f>IF(B5=&quot;&quot;,0,F5*&apos;단가&apos;!I5)</f><v>2000</v>",
      "<f>IF(B5=&quot;&quot;,0,F5*&apos;단가&apos;!I5)</f><v>999999</v>"
    )
  );

  // When
  const tampered = await zip.generateAsync({ type: "arraybuffer" });
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(tampered);
  const quantity = Number(workbook.getWorksheet("품목")?.getCell("F5").value);
  const unitPrice = Number(workbook.getWorksheet("단가")?.getCell("I5").result);
  const cachedAmount = Number(workbook.getWorksheet("품목")?.getCell("H5").result);

  // Then
  expect(quantity * unitPrice).toBe(2000);
  expect(cachedAmount).toBe(999999);
  expect(cachedAmount).not.toBe(quantity * unitPrice);
});
