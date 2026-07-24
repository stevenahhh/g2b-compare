import JSZip from "jszip";
import { describe, expect, it } from "vitest";
import {
  buildValidationReport,
  parseValidationReportBytes
} from "../../src/legacy/validation/index.js";
import { patchLegacyWorkbook } from "../../src/legacy/patch/index.js";
import {
  expectSuccess,
  mutateCell,
  scenarioRequest,
  scenarioSourcePath,
  sha256
} from "./validation-report-fixtures.js";

const WARNING_CODES = [
  "cached_formula_error",
  "formula_reference_error",
  "external_link",
  "problem_defined_name"
] as const;

describe("legacy validation report", () => {
  it("builds exact deterministic baseline reports for A/B/C", async () => {
    for (const id of ["A", "B", "C"] as const) {
      const request = await scenarioRequest(id);
      const first = expectSuccess(await buildValidationReport(request));
      const second = expectSuccess(await buildValidationReport(request));

      expect(first.reportBytes).toEqual(second.reportBytes);
      expect(first.reportSha256).toBe(sha256(first.reportBytes));
      expect(first.report.template.workbook_sha256).toBe(
        sha256(request.originalBytes)
      );
      expect(first.report.template.manifest_sha256).toBe(
        sha256(request.manifestBytes)
      );
      expect(first.report.output.workbook_sha256).toBe(
        sha256(request.outputBytes)
      );
      expect(first.report.output.formula_recalculated).toBe(false);
      expect(first.report.output.filename).toMatch(
        /_검토초안_미재계산[.]xlsx$/u
      );
      expect(first.report.changed_cells).toEqual([]);
      expect(first.report.official_sources).toEqual([]);
      expect(first.report.inherited_warnings.map(({ code }) => code)).toEqual(
        WARNING_CODES
      );
      expect(
        first.report.inherited_warnings.every(
          (warning) =>
            warning.output_count === warning.baseline_count &&
            warning.delta === 0
        )
      ).toBe(true);
      expect(first.report.validation).toEqual({
        status: "pass",
        unexpected_parts: 0,
        unexpected_cells: 0,
        unexpected_formulas: 0,
        unexpected_caches: 0,
        new_external_links: 0,
        unexpected_defined_names: 0,
        unexpected_vba: 0
      });
      expect(first.reportBytes.slice(0, 3)).not.toEqual(
        Uint8Array.from([0xef, 0xbb, 0xbf])
      );
      expect(parseValidationReportBytes(first.reportBytes)).toEqual(
        first.report
      );
    }
  }, 60_000);

  it("ignores ZIP container ordering and compression when part payloads match", async () => {
    const request = await scenarioRequest("A");
    const archive = await JSZip.loadAsync(request.originalBytes);
    const repacked = await archive.generateAsync({
      type: "uint8array",
      compression: "STORE"
    });

    const result = expectSuccess(
      await buildValidationReport({ ...request, outputBytes: repacked })
    );

    expect(result.report.output.workbook_sha256).not.toBe(
      result.report.template.workbook_sha256
    );
    expect(result.report.changed_cells).toEqual([]);
    expect(result.report.validation.status).toBe("pass");
  }, 30_000);

  it("sorts changed cells by original sheet, row, column and sources by id", async () => {
    const request = await scenarioRequest("A");
    const part = "xl/worksheets/sheet5.xml";
    const firstChange = await mutateCell(
      request.originalBytes,
      part,
      "N12",
      (cell) => cell.replace("<v>23903862</v>", "<v>23903863</v>")
    );
    const outputBytes = await mutateCell(
      firstChange,
      part,
      "B11",
      (cell) => cell.replace("<v>1</v>", "<v>2</v>")
    );

    const result = expectSuccess(
      await buildValidationReport({
        ...request,
        outputBytes,
        patchReceipt: {
          changedCells: [
            { sheet: "자재내역서", address: "N12" },
            { sheet: "자재내역서", address: "B11" }
          ],
          changedParts: [part]
        },
        officialSources: [
          {
            sourceId: "z-source",
            effectiveFrom: "2026-07-01",
            sha256:
              "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          },
          {
            sourceId: "a-source",
            effectiveFrom: "2026-01-01",
            sha256:
              "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
          }
        ]
      })
    );

    expect(result.report.changed_cells.map(({ address }) => address)).toEqual([
      "B11",
      "N12"
    ]);
    expect(
      result.report.official_sources.map(({ source_id }) => source_id)
    ).toEqual(["a-source", "z-source"]);
  }, 30_000);

  it("accepts the Task 9 receipt and validates its exact cache invalidations", async () => {
    const request = await scenarioRequest("A");
    const source = await scenarioSourcePath("A");
    const patched = await patchLegacyWorkbook({
      source,
      expectedSourceSha256: sha256(request.originalBytes),
      itemCount: 16,
      cells: [
        {
          sheet: "자재내역서",
          address: "G9",
          value: { kind: "number", value: "987654" }
        }
      ]
    });

    const result = expectSuccess(
      await buildValidationReport({
        ...request,
        outputBytes: patched.workbook,
        patchReceipt: patched.receipt
      })
    );

    expect(result.report.changed_cells).toHaveLength(
      patched.receipt.changedCells.length +
        patched.receipt.affectedFormulaCells.length
    );
    expect(result.report.validation.status).toBe("pass");
  }, 30_000);

  it("strictly parses UTF-8 schema v1.0 without extra properties", async () => {
    const request = await scenarioRequest("A");
    const success = expectSuccess(await buildValidationReport(request));
    const decoded = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(success.reportBytes)
    );

    expect(() =>
      parseValidationReportBytes(
        new TextEncoder().encode(JSON.stringify({ ...decoded, extra: true }))
      )
    ).toThrow();
    expect(() =>
      parseValidationReportBytes(
        Uint8Array.from([0xef, 0xbb, 0xbf, ...success.reportBytes])
      )
    ).toThrow();
    expect(() =>
      parseValidationReportBytes(new TextEncoder().encode("{"))
    ).toThrow();
    const validationLevelFormula = {
      ...decoded,
      validation: {
        ...decoded.validation,
        formula_recalculated: false
      }
    };
    expect(() =>
      parseValidationReportBytes(
        new TextEncoder().encode(JSON.stringify(validationLevelFormula))
      )
    ).toThrow();
    const misleading = {
      ...decoded,
      inherited_warnings: decoded.inherited_warnings.map(
        (warning: { readonly output_count: number }, index: number) =>
          index === 0
            ? { ...warning, output_count: warning.output_count + 1 }
            : warning
      )
    };
    expect(() =>
      parseValidationReportBytes(
        new TextEncoder().encode(JSON.stringify(misleading))
      )
    ).toThrow();
    expect(sha256(request.originalBytes)).toBe(
      sha256(request.originalBytes.slice())
    );
  }, 30_000);
});
