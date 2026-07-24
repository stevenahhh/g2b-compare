import { z } from "zod";
import { PatchCellInputSchema } from "../../legacy/patch/types.js";

const Sha256Schema = z.string().regex(/^[0-9a-f]{64}$/u);
const SafeFileNameSchema = z
  .string()
  .trim()
  .min(1)
  .max(255)
  .refine((name) => !/[\\/]/u.test(name));

export const LEGACY_PROFILE_FACTS = {
  A: {
    manifestName: "gwangyang-direct-2025.json",
    sourceSha256:
      "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    capacity: 16,
    totalWon: 39_149_530,
    layout: "13 + 3 품목(우수제품 13, 다수공급자 3) · 그룹 이동 금지"
  },
  B: {
    manifestName: "suncheon-procurement-2025.json",
    sourceSha256:
      "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    capacity: 9,
    totalWon: 20_284_000,
    layout: "9개 품목 · 4개 위치 · 3개 비교견적"
  },
  C: {
    manifestName: "gwangyang-procurement-final-2025.json",
    sourceSha256:
      "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    capacity: 24,
    totalWon: 65_854_000,
    layout: "24개 품목 · 1개 위치 · 3개 비교견적"
  }
} as const;

const LegacyEditableValueSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("blank") }).readonly(),
  z
    .strictObject({ kind: z.literal("text"), value: z.string() })
    .readonly(),
  z
    .strictObject({
      kind: z.literal("number"),
      value: z.string().regex(/^(?:0|[1-9]\d*)(?:\.\d+)?$/u)
    })
    .readonly()
]);

export const LegacyEditableCellSchema = z
  .strictObject({
    position: z.number().int().positive(),
    sheet: z.string().min(1),
    address: z.string().regex(/^[A-Z]+[1-9]\d*$/u),
    label: z.string().min(1),
    value: LegacyEditableValueSchema
  })
  .readonly();

export const LegacyImportSessionSchema = z
  .strictObject({
    schemaVersion: z.literal("legacy-ui-session-v1"),
    sessionId: z.string().uuid(),
    sourceName: SafeFileNameSchema,
    profileId: z.enum(["A", "B", "C"]),
    profileSlug: z.string().min(1),
    sourceSha256: Sha256Schema,
    capacity: z.number().int().positive(),
    itemCount: z.number().int().nonnegative(),
    totalWon: z.number().int().positive(),
    layout: z.string().min(1),
    editableCells: z.array(LegacyEditableCellSchema).readonly(),
    warnings: z
      .strictObject({
        externalLinks: z.number().int().nonnegative(),
        cachedFormulaErrors: z.number().int().nonnegative(),
        formulaReferenceErrors: z.number().int().nonnegative(),
        problemDefinedNames: z.number().int().nonnegative(),
        inheritedFormulaCells: z.array(z.string()).readonly(),
        disposition: z.string().min(1)
      })
      .readonly()
  })
  .superRefine((session, context) => {
    const facts = LEGACY_PROFILE_FACTS[session.profileId];
    if (
      session.sourceSha256 !== facts.sourceSha256 ||
      session.capacity !== facts.capacity ||
      session.totalWon !== facts.totalWon ||
      session.layout !== facts.layout ||
      session.itemCount > facts.capacity
    ) {
      context.addIssue({
        code: "custom",
        message: "LEGACY_PROFILE_FACTS_MISMATCH"
      });
    }
  })
  .readonly();

export const LegacyExportRequestSchema = z
  .strictObject({
    kind: z.literal("legacy_workbook"),
    capabilityId: z.string().uuid(),
    sessionId: z.string().uuid(),
    itemCount: z.number().int().nonnegative(),
    cells: z.array(PatchCellInputSchema).readonly(),
    disclaimerChecked: z.boolean()
  })
  .readonly();

export const LEGACY_WORKFLOW_ERROR_CODES = [
  "SOURCE_OVERWRITE_FORBIDDEN",
  "PROFILE_CAPACITY_EXCEEDED",
  "GROUP_BOUNDARY_BREACH",
  "COMPARISON_REQUIRED",
  "DISCLAIMER_REQUIRED",
  "EXPORT_FAILED"
] as const;

export const LegacyWorkflowFailureSchema = z
  .strictObject({
    errorCode: z.enum(LEGACY_WORKFLOW_ERROR_CODES),
    message: z.string().min(1),
    finalFilesPublished: z.literal(0)
  })
  .readonly();

export type LegacyEditableCell = z.output<typeof LegacyEditableCellSchema>;
export type LegacyImportSession = z.output<typeof LegacyImportSessionSchema>;
export type LegacyExportRequest = z.output<typeof LegacyExportRequestSchema>;
export type LegacyWorkflowErrorCode =
  (typeof LEGACY_WORKFLOW_ERROR_CODES)[number];
