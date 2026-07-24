import { describe, expect, it } from "vitest";
import {
  buildValidationReport,
  type ValidationErrorCode,
  type ValidationReportRequest
} from "../../src/legacy/validation/index.js";
import {
  addPart,
  mutateCell,
  mutatePart,
  scenarioRequest,
  sha256
} from "./validation-report-fixtures.js";

async function expectFailure(
  request: ValidationReportRequest,
  code: ValidationErrorCode
): Promise<void> {
  const beforeOriginal = sha256(request.originalBytes);
  const beforeOutput = sha256(request.outputBytes);
  const result = await buildValidationReport(request);

  expect(result.ok).toBe(false);
  if (result.ok) {
    throw new TypeError("Expected validation failure");
  }
  expect(result.errors).toContain(code);
  expect("reportBytes" in result).toBe(false);
  expect(sha256(request.originalBytes)).toBe(beforeOriginal);
  expect(sha256(request.outputBytes)).toBe(beforeOutput);
}

describe("legacy validation report rejection", () => {
  it("rejects malformed ZIP and stale manifest hash or inventory", async () => {
    const request = await scenarioRequest("A");
    await expectFailure(
      { ...request, outputBytes: Buffer.from("not-a-zip") },
      "MALFORMED_ZIP"
    );

    const manifest = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(request.manifestBytes)
    );
    await expectFailure(
      {
        ...request,
        manifestBytes: new TextEncoder().encode(
          JSON.stringify({
            ...manifest,
            source: { ...manifest.source, sha256: "0".repeat(64) }
          })
        )
      },
      "TEMPLATE_HASH_MISMATCH"
    );
    await expectFailure(
      {
        ...request,
        manifestBytes: new TextEncoder().encode(
          JSON.stringify({
            ...manifest,
            baselineInventory: {
              ...manifest.baselineInventory,
              externalLinks: {
                ...manifest.baselineInventory.externalLinks,
                count: manifest.baselineInventory.externalLinks.count + 1
              }
            }
          })
        )
      },
      "STALE_MANIFEST"
    );
  }, 30_000);

  it("rejects unexpected cell, formula, cache, and part drift", async () => {
    const request = await scenarioRequest("A");
    const part = "xl/worksheets/sheet5.xml";
    const unexpectedCell = await mutateCell(
      request.originalBytes,
      part,
      "H9",
      (cell) => cell.replace("+G9*F9", "+G9*F8")
    );
    await expectFailure(
      {
        ...request,
        outputBytes: unexpectedCell,
        patchReceipt: {
          changedCells: [{ sheet: "자재내역서", address: "H9" }],
          changedParts: [part],
          formulaCells: [{ sheet: "자재내역서", address: "H9" }]
        }
      },
      "UNEXPECTED_CELL_DRIFT"
    );
    await expectFailure(
      {
        ...request,
        outputBytes: unexpectedCell,
        patchReceipt: {
          changedCells: [{ sheet: "자재내역서", address: "H9" }],
          changedParts: [part]
        }
      },
      "UNEXPECTED_FORMULA_DRIFT"
    );

    const unexpectedCache = await mutateCell(
      request.originalBytes,
      part,
      "H9",
      (cell) => cell.replace(/<v>[^<]*<[/]v>/u, "<v>999</v>")
    );
    await expectFailure(
      {
        ...request,
        outputBytes: unexpectedCache,
        patchReceipt: {
          changedCells: [{ sheet: "자재내역서", address: "H9" }],
          changedParts: [part]
        }
      },
      "UNEXPECTED_CACHE_DRIFT"
    );

    const unexpectedPart = await addPart(
      request.originalBytes,
      "docProps/injected.xml",
      "<injected/>"
    );
    await expectFailure(
      { ...request, outputBytes: unexpectedPart },
      "UNEXPECTED_PART_DRIFT"
    );
  }, 30_000);

  it("rejects new external links, defined-name fingerprint drift, and VBA", async () => {
    const request = await scenarioRequest("A");
    const externalPart = "xl/externalLinks/externalLink999.xml";
    const external = await addPart(
      request.originalBytes,
      externalPart,
      '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
    );
    await expectFailure(
      {
        ...request,
        outputBytes: external,
        patchReceipt: { changedCells: [], changedParts: [externalPart] }
      },
      "NEW_EXTERNAL_LINK"
    );

    const workbookPart = "xl/workbook.xml";
    const changedName = await mutatePart(
      request.originalBytes,
      workbookPart,
      (xml) => xml.replace("#REF!", "#NAME?")
    );
    await expectFailure(
      {
        ...request,
        outputBytes: changedName,
        patchReceipt: { changedCells: [], changedParts: [workbookPart] }
      },
      "UNEXPECTED_DEFINED_NAME_DRIFT"
    );

    const vbaPart = "xl/vbaProject.bin";
    const vba = await addPart(
      request.originalBytes,
      vbaPart,
      Uint8Array.from([1, 2, 3])
    );
    await expectFailure(
      {
        ...request,
        outputBytes: vba,
        patchReceipt: { changedCells: [], changedParts: [vbaPart] }
      },
      "UNEXPECTED_VBA_DRIFT"
    );
  }, 30_000);

  it("rejects stale receipts, invalid values, and interrupted report inputs", async () => {
    const request = await scenarioRequest("A");
    await expectFailure(
      {
        ...request,
        patchReceipt: {
          changedCells: [{ sheet: "자재내역서", address: "B11" }],
          changedParts: []
        }
      },
      "PATCH_RECEIPT_MISMATCH"
    );
    await expectFailure(
      {
        ...request,
        patchReceipt: {
          changedCells: [],
          changedParts: [],
          outputSha256:
            "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        }
      },
      "PATCH_RECEIPT_MISMATCH"
    );
    await expectFailure(
      { ...request, outputFilename: "unsafe.xlsx" },
      "INVALID_REPORT_INPUT"
    );
    await expectFailure(
      { ...request, generatedAtUtc: "interrupted" },
      "INVALID_REPORT_INPUT"
    );
  }, 30_000);
});
