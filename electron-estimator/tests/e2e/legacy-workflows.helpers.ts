import type { ElectronApplication } from "@playwright/test";
import { expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import type ExcelJS from "exceljs";

export async function useDialogPaths(
  application: ElectronApplication,
  source: string,
  destination: string
): Promise<void> {
  await application.evaluate(
    ({ dialog }, paths) => {
      Object.defineProperty(dialog, "showOpenDialog", {
        configurable: true,
        value: async () => ({ canceled: false, filePaths: [paths.source] })
      });
      Object.defineProperty(dialog, "showSaveDialog", {
        configurable: true,
        value: async () => ({
          canceled: false,
          filePath: paths.destination
        })
      });
    },
    { source, destination }
  );
}

export async function sha256(file: string): Promise<string> {
  return createHash("sha256").update(await readFile(file)).digest("hex");
}

export async function expectNoPublishedPair(workbook: string): Promise<void> {
  await expect(access(workbook)).rejects.toThrow();
  await expect(access(workbook.replace(/[.]xlsx$/u, ".validation.json")))
    .rejects.toThrow();
}

export async function expectNoSidecar(workbook: string): Promise<void> {
  await expect(access(workbook.replace(/[.]xlsx$/u, ".validation.json")))
    .rejects.toThrow();
}

export function excelNumber(value: ExcelJS.CellValue | undefined): number {
  const result =
    typeof value === "object" && value !== null && "result" in value
      ? Reflect.get(value, "result")
      : value;
  return Number(result);
}
