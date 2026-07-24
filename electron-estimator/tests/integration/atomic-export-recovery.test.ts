import {
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile
} from "node:fs/promises";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  exportLegacyWorkbook,
  recoverInterruptedExports
} from "../../src/legacy/export/index.js";
import {
  exportFixture,
  journalRootFor,
  removeTemporaryDirectory,
  temporaryExportDirectory
} from "./atomic-export-fixtures.js";
import { killBetweenRenames } from "./atomic-export-crash-helpers.js";

const directories: string[] = [];
const journalRoots: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map(removeTemporaryDirectory));
  await Promise.all(
    journalRoots.splice(0).map((path) =>
      rm(path, { recursive: true, force: true })
    )
  );
});

describe("interrupted legacy export recovery", () => {
  it("recovers before retrying any new export work", async () => {
    const { directory, journalRoot } = await crashWorkspace();
    await killBetweenRenames(directory, journalRoot);
    const request = await exportFixture("A", directory, "retry-A");

    const result = await exportLegacyWorkbook(request, { journalRoot });

    expect(result.ok).toBe(true);
    expect((await readdir(directory)).toSorted()).toEqual([
      "killed-A_검토초안_미재계산.validation.json",
      "killed-A_검토초안_미재계산.xlsx",
      "retry-A_검토초안_미재계산.validation.json",
      "retry-A_검토초안_미재계산.xlsx"
    ]);
    expect(await readdir(journalRoot)).toEqual([]);
  }, 60_000);

  it("removes stale valid journals without touching unrelated files", async () => {
    const { directory, journalRoot } = await crashWorkspace();
    await killBetweenRenames(directory, journalRoot);
    for (const name of await readdir(directory)) {
      await rm(join(directory, name));
    }
    const unrelated = join(directory, "keep.txt");
    await writeFile(unrelated, "keep");

    const result = await recoverInterruptedExports({ journalRoot });

    expect(result).toMatchObject({
      ok: true,
      receipt: {
        scannedTransactions: 1,
        recoveredTransactions: 1,
        cleanupComplete: true
      }
    });
    expect(await readFile(unrelated, "utf8")).toBe("keep");
    expect(await readdir(journalRoot)).toEqual([]);
  }, 60_000);

  it("rejects corrupt journals without following untrusted paths", async () => {
    const directory = await temporaryExportDirectory();
    const journalRoot = journalRootFor(directory);
    const transactionId = "11111111-1111-4111-8111-111111111111";
    const transactionDirectory = join(journalRoot, transactionId);
    directories.push(directory);
    journalRoots.push(journalRoot);
    await mkdir(transactionDirectory, { recursive: true });
    await writeFile(
      join(transactionDirectory, "journal.jsonl"),
      "not-json\n"
    );
    const unrelated = join(directory, "keep.txt");
    await writeFile(unrelated, "keep");

    const result = await recoverInterruptedExports({ journalRoot });

    expect(result).toMatchObject({
      ok: false,
      receipt: {
        rejectedTransactions: 1,
        cleanupComplete: false
      }
    });
    expect(await readFile(unrelated, "utf8")).toBe("keep");
    expect(await readdir(journalRoot)).toEqual([transactionId]);
  });

  it("refuses a schema-valid journal aimed at unrelated files", async () => {
    const directory = await temporaryExportDirectory();
    const journalRoot = journalRootFor(directory);
    const transactionId = "11111111-1111-4111-8111-111111111111";
    const transactionDirectory = join(journalRoot, transactionId);
    const source = join(directory, "unrelated-source.xlsx");
    const workbook = join(
      directory,
      "unrelated_검토초안_미재계산.xlsx"
    );
    const report = join(
      directory,
      "unrelated_검토초안_미재계산.validation.json"
    );
    const workbookTemporary = join(
      transactionDirectory,
      `${transactionId}.workbook.tmp`
    );
    const reportTemporary = join(
      transactionDirectory,
      `${transactionId}.report.tmp`
    );
    directories.push(directory);
    journalRoots.push(journalRoot);
    await mkdir(transactionDirectory, { recursive: true });
    await Promise.all([
      writeFile(source, "unrelated-source"),
      writeFile(workbook, "unrelated-workbook"),
      writeFile(report, "unrelated-report"),
      writeFile(workbookTemporary, "unrelated-workbook-temp"),
      writeFile(reportTemporary, "unrelated-report-temp")
    ]);
    await writeFile(
      join(transactionDirectory, "journal.jsonl"),
      `${JSON.stringify({
        schemaVersion: "atomic-legacy-export-journal-v2",
        transactionId,
        transactionDirectory,
        state: "workbook-publishing",
        paths: {
          source,
          workbook,
          report,
          workbookTemporary,
          reportTemporary
        },
        proof: {
          outputFilename: "unrelated_검토초안_미재계산.xlsx",
          sourceSha256: "0".repeat(64),
          templateSha256: "0".repeat(64),
          outputSha256: "0".repeat(64),
          reportSha256: "0".repeat(64)
        }
      })}\n`
    );

    const result = await recoverInterruptedExports({ journalRoot });

    expect(result.ok).toBe(false);
    await expect(readFile(workbook, "utf8")).resolves.toBe(
      "unrelated-workbook"
    );
    await expect(readFile(report, "utf8")).resolves.toBe("unrelated-report");
    await expect(readFile(workbookTemporary, "utf8")).resolves.toBe(
      "unrelated-workbook-temp"
    );
    await expect(readFile(reportTemporary, "utf8")).resolves.toBe(
      "unrelated-report-temp"
    );
    await expect(readFile(source, "utf8")).resolves.toBe("unrelated-source");
  });
});

async function crashWorkspace(): Promise<{
  readonly directory: string;
  readonly journalRoot: string;
}> {
  const directory = await temporaryExportDirectory();
  const journalRoot = journalRootFor(directory);
  directories.push(directory);
  journalRoots.push(journalRoot);
  return { directory, journalRoot };
}
