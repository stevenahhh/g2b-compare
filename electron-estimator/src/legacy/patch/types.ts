import { z } from "zod";
import type { LegacyCellValue } from "../inspect/types.js";

const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const DECIMAL_PATTERN = /^(?:0|[1-9]\d*)(?:\.\d+)?$/u;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/u;

const TextValueSchema = z
  .strictObject({
    kind: z.literal("text"),
    value: z.string().refine(isXmlText, { message: "PATCH_VALUE_INVALID" })
  })
  .readonly();

const NumberValueSchema = z
  .strictObject({
    kind: z.literal("number"),
    value: z.string().regex(DECIMAL_PATTERN, {
      message: "PATCH_VALUE_INVALID"
    })
  })
  .readonly();

const DateValueSchema = z
  .strictObject({
    kind: z.literal("date"),
    value: z.string().regex(DATE_PATTERN, {
      message: "PATCH_VALUE_INVALID"
    }).refine(isCalendarDate, { message: "PATCH_VALUE_INVALID" })
  })
  .readonly();

const BlankValueSchema = z
  .strictObject({ kind: z.literal("blank") })
  .readonly();

export const PatchCellValueSchema = z.discriminatedUnion("kind", [
  TextValueSchema,
  NumberValueSchema,
  DateValueSchema,
  BlankValueSchema
]);

export const PatchCellInputSchema = z
  .strictObject({
    sheet: z.string().min(1),
    address: z.string().regex(/^[A-Z]+[1-9]\d*$/u),
    value: PatchCellValueSchema
  })
  .readonly();

export const PatchLegacyWorkbookInputSchema = z
  .strictObject({
    source: z.union([z.string().min(1), z.instanceof(URL)]),
    expectedSourceSha256: z.string().regex(SHA256_PATTERN),
    itemCount: z.number().int().nonnegative(),
    cells: z.array(PatchCellInputSchema).readonly()
  })
  .readonly();

export type PatchCellValue = z.output<typeof PatchCellValueSchema>;
export type PatchCellInput = z.output<typeof PatchCellInputSchema>;
export type PatchLegacyWorkbookInput =
  z.output<typeof PatchLegacyWorkbookInputSchema>;

export type PatchCellCoordinate = {
  readonly sheet: string;
  readonly address: string;
};

export type ChangedCellReceipt = PatchCellCoordinate & {
  readonly before: LegacyCellValue;
  readonly after: PatchCellValue;
};

export type PatchReceipt = {
  readonly schemaVersion: "legacy-ooxml-patch-v1";
  readonly profileId: "A" | "B" | "C";
  readonly sourceSha256: string;
  readonly outputSha256: string;
  readonly changedCells: readonly ChangedCellReceipt[];
  readonly affectedFormulaCells: readonly PatchCellCoordinate[];
  readonly changedParts: readonly string[];
};

export type PatchedLegacyWorkbook = {
  readonly workbook: Uint8Array;
  readonly receipt: PatchReceipt;
};

function isCalendarDate(value: string): boolean {
  const [yearText, monthText, dayText] = value.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const timestamp = Date.UTC(year, month - 1, day);
  const parsed = new Date(timestamp);
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function isXmlText(value: string): boolean {
  for (const character of value) {
    const code = character.codePointAt(0);
    if (
      code === undefined ||
      (
        code !== 0x9 &&
        code !== 0xa &&
        code !== 0xd &&
        (code < 0x20 || code > 0xd7ff) &&
        (code < 0xe000 || code > 0xfffd) &&
        (code < 0x10000 || code > 0x10ffff)
      )
    ) {
      return false;
    }
  }
  return true;
}

