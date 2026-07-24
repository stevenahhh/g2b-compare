import {
  copyFile,
  link,
  readFile,
  readdir,
  writeFile
} from "node:fs/promises";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  exportLegacyWorkbook,
  type AtomicLegacyExportRequest
} from "../../src/legacy/export/index.js";
import {
  exportFixture,
  exportOptions,
  fileSha256,
  removeTemporaryDirectory,
  temporaryExportDirectory
} from "./atomic-export-fixtures.js";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(directories.splice(0).map(removeTemporaryDirectory));
});

describe("atomic legacy export boundary", () => {
  it("requires the explicit disclaimer before any write", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const request = await exportFixture("A", directory);
    let writeStages = 0;

    const result = await exportLegacyWorkbook({
      ...request,
      disclaimer: { ...request.disclaimer, checked: false }
    }, exportOptions(directory, {
      beforeStage: async (stage) => {
        if (stage.includes("write")) {
          writeStages += 1;
        }
      }
    }));

    expect(result).toMatchObject({
      ok: false,
      error: { code: "EXPORT_DISCLAIMER_REQUIRED" }
    });
    expect(writeStages).toBe(0);
    expect(await readdir(directory)).toEqual([]);
  });

  it("rejects malformed and traversal paths without writing", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const request = await exportFixture("A", directory);
    const malformed: readonly unknown[] = [
      {},
      { ...request, destinationPath: "relative.xlsx" },
      {
        ...request,
        destinationPath:
          `${directory}\\..\\escape_검토초안_미재계산.xlsx`
      },
      {
        ...request,
        destinationPath: join(directory, "wrong.xlsx")
      },
      { ...request, expectedSourceSha256: "not-a-hash" }
    ];

    for (const candidate of malformed) {
      const result = await exportLegacyWorkbook(
        candidate,
        exportOptions(directory)
      );
      expect(result).toMatchObject({
        ok: false,
        error: { code: "INVALID_EXPORT_REQUEST" }
      });
    }
    expect(await readdir(directory)).toEqual([]);
  });

  it("rejects a transaction journal inside the destination", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const request = await exportFixture("A", directory);

    const result = await exportLegacyWorkbook(request, {
      journalRoot: directory
    });

    expect(result).toMatchObject({
      ok: false,
      error: { code: "INVALID_EXPORT_REQUEST" }
    });
    expect(await readdir(directory)).toEqual([]);
  });

  it("rejects same-path, case alias, and hardlink destinations", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const base = await exportFixture("A", directory);
    const samePath = join(directory, "Same_검토초안_미재계산.xlsx");
    await copyFile(base.sourcePath, samePath);
    const sameRequest: AtomicLegacyExportRequest = {
      ...base,
      sourcePath: samePath,
      destinationPath: samePath
    };

    const same = await exportLegacyWorkbook(
      sameRequest,
      exportOptions(directory)
    );
    const caseAlias = await exportLegacyWorkbook({
      ...sameRequest,
      destinationPath: samePath.toLowerCase()
    }, exportOptions(directory));

    expect(same).toMatchObject({
      ok: false,
      error: { code: "SOURCE_DESTINATION_CONFLICT" }
    });
    expect(caseAlias).toMatchObject({
      ok: false,
      error: { code: "SOURCE_DESTINATION_CONFLICT" }
    });

    const hardlinkPath = join(
      directory,
      "hardlink_검토초안_미재계산.xlsx"
    );
    await link(base.sourcePath, hardlinkPath);
    const hardlinkResult = await exportLegacyWorkbook({
      ...base,
      destinationPath: hardlinkPath
    }, exportOptions(directory));
    expect(hardlinkResult).toMatchObject({
      ok: false,
      error: { code: "SOURCE_DESTINATION_CONFLICT" }
    });
  });

  it("never overwrites existing finals and aborts stale source/manifest", async () => {
    const directory = await temporaryExportDirectory();
    directories.push(directory);
    const collision = await exportFixture("A", directory, "collision");
    const reportPath = collision.destinationPath.replace(
      /[.]xlsx$/u,
      ".validation.json"
    );
    await writeFile(collision.destinationPath, "existing workbook");
    await writeFile(reportPath, "existing report");

    const collisionResult = await exportLegacyWorkbook(
      collision,
      exportOptions(directory)
    );

    expect(collisionResult).toMatchObject({
      ok: false,
      error: { code: "DESTINATION_EXISTS" }
    });
    expect(await readFile(collision.destinationPath, "utf8")).toBe(
      "existing workbook"
    );
    expect(await readFile(reportPath, "utf8")).toBe("existing report");

    const staleDirectory = await temporaryExportDirectory();
    directories.push(staleDirectory);
    const stale = await exportFixture("A", staleDirectory, "stale");
    const other = await exportFixture("B", staleDirectory, "other");
    const staleResult = await exportLegacyWorkbook({
      ...stale,
      manifestBytes: other.manifestBytes
    }, exportOptions(staleDirectory));
    expect(staleResult).toMatchObject({
      ok: false,
      error: { code: "ATOMIC_EXPORT_ABORTED" }
    });
    expect(await readdir(staleDirectory)).toEqual([]);
    expect(await fileSha256(stale.sourcePath)).toBe(
      stale.expectedSourceSha256
    );
  }, 30_000);
});
