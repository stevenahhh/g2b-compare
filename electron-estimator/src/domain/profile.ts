import { z } from "zod";
import { parsePositiveWon, parseRate } from "./money.js";

export const LEGACY_PROFILE_NATIVE_SETTINGS = {
  A: {
    revision: "445012e259ab5318a1d52468cce93ee28a55a8bcb467876f40a47a939e4668db",
    capacity: 16,
    feePolicy: { kind: "fee_up", rate: "0.0054", incrementWon: "1000" },
    oracle: { subtotalWon: "38938530", totalWon: "39149530" }
  },
  B: {
    revision: "2220cd9936ebdf908d64c0571a4c8de83973eaa89c6778a64afec07de7c5e701",
    capacity: 9,
    feePolicy: { kind: "total_up", rate: "0.0054", incrementWon: "1000" },
    oracle: { subtotalWon: "20174460", totalWon: "20284000" }
  },
  C: {
    revision: "8a55700bdaf62a00c208c7286531fd56ca321571f73f7620505a823ef5d4d0f1",
    capacity: 24,
    feePolicy: { kind: "total_up", rate: "0.0054", incrementWon: "1000" },
    oracle: { subtotalWon: "65499660", totalWon: "65854000" }
  }
} as const;

const NativeRateSchema = z
  .literal(LEGACY_PROFILE_NATIVE_SETTINGS.A.feePolicy.rate)
  .transform(parseRate);
const NativeIncrementSchema = z
  .literal(LEGACY_PROFILE_NATIVE_SETTINGS.A.feePolicy.incrementWon)
  .transform(parsePositiveWon);
const NativeFeeUpSchema = z
  .strictObject({
    kind: z.literal("fee_up"),
    rate: NativeRateSchema,
    incrementWon: NativeIncrementSchema
  })
  .readonly();
const NativeTotalUpSchema = z
  .strictObject({
    kind: z.literal("total_up"),
    rate: NativeRateSchema,
    incrementWon: NativeIncrementSchema
  })
  .readonly();
export const EstimateProfileSchema = z.discriminatedUnion("id", [
  z
    .strictObject({
      id: z.literal("A"),
      revision: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.A.revision),
      capacity: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.A.capacity),
      feePolicy: NativeFeeUpSchema
    })
    .readonly(),
  z
    .strictObject({
      id: z.literal("B"),
      revision: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.B.revision),
      capacity: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.B.capacity),
      feePolicy: NativeTotalUpSchema
    })
    .readonly(),
  z
    .strictObject({
      id: z.literal("C"),
      revision: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.C.revision),
      capacity: z.literal(LEGACY_PROFILE_NATIVE_SETTINGS.C.capacity),
      feePolicy: NativeTotalUpSchema
    })
    .readonly()
]);
