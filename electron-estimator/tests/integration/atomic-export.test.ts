import { copyFile, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  ATOMIC_EXPORT_STAGES,
  exportLegacyWorkbook
} from "../../src/legacy/export/index.js";
import { parseValidationReportBytes } from "../../src/legacy/validation/index.js";
import {
  exportFixture,
  exportOptions,
  fileSha256,
  journalEntries,
  journalRootFor,
  removeTemporaryDirectory,
  sha256,
  temporaryExportDirectory
} from "./atomic-export-fixtures.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map(removeTemporaryDirectory));
});

describe("atomic legacy export", () => {
  it("publishes workbook and report for exact A/B/C profiles", async () => {
    for (const id of ["A", "B", "C"] as const) {
      const directory = await temporaryExportDirectory();
      directories.push(directory);
      const request = await exportFixture(id, directory);
      const sourceBefore = await fileSha256(request.sourcePath);

      const result = await exportLegacyWorkbook(
        request,
        exportOptions(directory)
      );

      expect(result.ok).toBe(true);
      if (!result.ok) {
        continue;
      }
      const files = await readdir(directory);
      expect(files.toSorted()).toEqual([
        result.validationReportName,
        result.workbookName
      ].toSorted());
      expect(files.filter((name) => name.endsWith(".tmp"))).toEqual([]);
      const workbookPath = join(directory, result.workbookName);
      const reportPath = join(directory, result.validationReportName);
      const workbookBytes = await readFile(workbookPath);
      const reportBytes = await readFile(reportPath);
      const report = parseValidationReportBytes(reportBytes);
      expect(result.workbookName).toBe(basename(request.destinationPath));
      expect(result.validationReportName).toBe(
        basename(request.destinationPath).replace(
          /[.]xlsx$/u,
          ".validation.json"
        )
      );
      expect(result.workbookSha256).toBe(sha256(workbookBytes));
      expect(result.validationReportSha256).toBe(sha256(reportBytes));
      expect(report.output.workbook_sha256).toBe(result.workbookSha256);
      expect(report.output.filename).toBe(result.workbookName);
      expect(report.output.formula_recalculated).toBe(false);
      expect(report.validation.status).toBe("pass");
      expect(result.cleanup).toEqual({
        temporaryFilesCreated: 2,
        temporaryFilesRemoved: 2,
        finalFilesPublished: 2,
        finalFilesRolledBack: 0,
        complete: true
      });
      expect(await fileSha256(request.sourcePath)).toBe(sourceBefore);
      expect(await journalEntries(directory)).toEqual([]);
      expect(JSON.stringify(result)).not.toContain(request.sourcePath);
      expect(JSON.stringify(result)).not.toContain(directory);
    }
  }, 120_000);

  it("produces deterministic report bytes for identical export facts", async () => {
    const firstDirectory = await temporaryExportDirectory();
    const secondDirectory = await temporaryExportDirectory();
    directories.push(firstDirectory, secondDirectory);
    const firstRequest = await exportFixture("A", firstDirectory, "same");
    const secondRequest = await exportFixture("A", secondDirectory, "same");

    const first = await exportLegacyWorkbook(
      firstRequest,
      exportOptions(firstDirectory)
    );
    const second = await exportLegacyWorkbook(
      secondRequest,
      exportOptions(secondDirectory)
    );

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (first.ok && second.ok) {
      expect(
        await readFile(join(firstDirectory, first.validationReportName))
      ).toEqual(
        await readFile(join(secondDirectory, second.validationReportName))
      );
    }
  }, 60_000);

  it("rolls back every fault point", async () => {
    for (const stage of ATOMIC_EXPORT_STAGES) {
      const directory = await temporaryExportDirectory();
      directories.push(directory);
      const request = await exportFixture("A", directory, `fault-${stage}`);
      const sourceBefore = await fileSha256(request.sourcePath);

      const result = await exportLegacyWorkbook(request, exportOptions(
        directory,
        {
        beforeStage: async (current) => {
          if (current === stage) {
            throw new TypeError(`induced ${stage}`);
          }
        }
        }
      ));

      expect(result).toMatchObject({
        ok: false,
        error: { code: "ATOMIC_EXPORT_ABORTED" },
        cleanup: { complete: true }
      });
      expect(await readdir(directory)).toEqual([]);
      expect(await journalEntries(directory)).toEqual([]);
      expect(await fileSha256(request.sourcePath)).toBe(sourceBefore);
    }
  }, 120_000);

  it("rejects corrupt workbook/report verification and long writes", async () => {
    for (const stage of ["verify-workbook", "verify-report"] as const) {
      const directory = await temporaryExportDirectory();
      directories.push(directory);
      const request = await exportFixture("A", directory, `corrupt-${stage}`);
      const result = await exportLegacyWorkbook(request, exportOptions(
        directory,
        {
        beforeStage: async (current) => {
          if (current !== stage) {
            return;
          }
          const transaction = (await readdir(journalRootFor(directory)))[0];
          if (transaction === undefined) {
            return;
          }
          const transactionDirectory = join(
            journalRootFor(directory),
            transaction
          );
          const temporary = (await readdir(transactionDirectory)).find((name) =>
            stage === "verify-workbook"
              ? name.endsWith(".workbook.tmp")
              : name.endsWith(".report.tmp")
          );
          if (temporary !== undefined) {
            await writeFile(
              join(transactionDirectory, temporary),
              "corrupt"
            );
          }
        }
        }
      ));
      expect(result).toMatchObject({
        ok: false,
        error: { code: "ATOMIC_EXPORT_ABORTED" }
      });
      expect(await readdir(directory)).toEqual([]);
      expect(await journalEntries(directory)).toEqual([]);
    }

    const timeoutDirectory = await temporaryExportDirectory();
    directories.push(timeoutDirectory);
    const timeoutRequest = await exportFixture("A", timeoutDirectory, "slow");
    const timeout = await exportLegacyWorkbook(timeoutRequest, exportOptions(
      timeoutDirectory,
      {
      timeoutMs: 20,
      beforeStage: (stage) =>
        stage === "workbook-write"
          ? new Promise<void>(() => undefined)
          : Promise.resolve()
      }
    ));
    expect(timeout).toMatchObject({
      ok: false,
      error: { code: "ATOMIC_EXPORT_ABORTED" }
    });
    expect(await readdir(timeoutDirectory)).toEqual([]);
    expect(await journalEntries(timeoutDirectory)).toEqual([]);
  }, 60_000);

  it("rejects source overwrite at the same path before publication", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const base = await exportFixture("A", directory, "same-path");
    const scratchSource = join(
      directory,
      "same-path_검토초안_미재계산.xlsx"
    );
    await copyFile(base.sourcePath, scratchSource);
    const sourceBefore = await fileSha256(scratchSource);

    const result = await exportLegacyWorkbook(
      {
        ...base,
        sourcePath: scratchSource,
        destinationPath: scratchSource
      },
      exportOptions(directory)
    );

    expect(result).toMatchObject({
      ok: false,
      error: { code: "SOURCE_DESTINATION_CONFLICT" }
    });
    expect(await fileSha256(scratchSource)).toBe(sourceBefore);
    expect((await readdir(directory)).toSorted()).toEqual([
      "same-path_검토초안_미재계산.xlsx"
    ]);
  });
});
