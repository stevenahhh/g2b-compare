import Decimal from "decimal.js";
import { z } from "zod";
import {
  calculateProfileTotal,
  QuantitySchema,
  selectThreeCompanyMinimum,
  type ProfileTotal
} from "./money.js";
import { EstimateProfileSchema } from "./profile.js";
import {
  MarketPriceProvenanceSchema,
  quoteSourceIdentity,
  QuoteSourceSchema,
  RateContextSchema,
  StandardQuantityProvenanceSchema,
  ThreeCompanyMinimumProvenanceSchema,
  type Provenance
} from "./provenance.js";

export {
  EstimateProfileSchema,
  LEGACY_PROFILE_NATIVE_SETTINGS
} from "./profile.js";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u;
const NonemptySchema = z.string().trim().min(1);
const IdSchema = z.string().regex(ID_PATTERN, { message: "INVALID_ID" });

export const LineRoleSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("main") }).readonly(),
  z
    .strictObject({ kind: z.literal("bound_option"), parentLineId: IdSchema })
    .readonly(),
  z.strictObject({ kind: z.literal("unbound_option") }).readonly()
]);

const DirectCostSchema = z
  .strictObject({
    kind: z.literal("direct"),
    provenance: QuoteSourceSchema
  })
  .readonly();

const ThreeCompanyCostSchema = z
  .strictObject({
    kind: z.literal("three_company_min"),
    quotes: z
      .tuple([
        quoteCandidate("A"),
        quoteCandidate("B"),
        quoteCandidate("C")
      ])
      .readonly()
  })
  .readonly();

const MarketPriceCostSchema = z
  .strictObject({
    kind: z.literal("market_price"),
    provenance: MarketPriceProvenanceSchema,
    rateContext: RateContextSchema
  })
  .readonly();

const StandardQuantityCostSchema = z
  .strictObject({
    kind: z.literal("standard_quantity"),
    provenance: StandardQuantityProvenanceSchema,
    rateContext: RateContextSchema
  })
  .readonly();

export const CostMethodSchema = z.discriminatedUnion("kind", [
  DirectCostSchema,
  ThreeCompanyCostSchema,
  MarketPriceCostSchema,
  StandardQuantityCostSchema
]);

export const EstimateLineSchema = z
  .strictObject({
    id: IdSchema,
    role: LineRoleSchema,
    itemName: NonemptySchema,
    specification: NonemptySchema,
    unit: NonemptySchema,
    quantity: QuantitySchema,
    cost: CostMethodSchema
  })
  .readonly();

export const EstimateInputSchema = z
  .strictObject({
    id: IdSchema,
    revision: z.number().int().nonnegative(),
    profile: EstimateProfileSchema,
    lines: z.array(EstimateLineSchema).readonly()
  })
  .readonly();

export type Estimate = z.output<typeof EstimateInputSchema>;
export type EstimateLine = z.output<typeof EstimateLineSchema>;

export type LineCalculation = {
  readonly id: string;
  readonly role: EstimateLine["role"];
  readonly unitCostWon: Decimal;
  readonly subtotalWon: Decimal;
  readonly provenance: Provenance;
};

export type EstimateCalculation = {
  readonly estimateId: string;
  readonly revision: number;
  readonly lines: readonly LineCalculation[];
  readonly subtotalWon: Decimal;
  readonly total: ProfileTotal;
};

export class EstimateCalculationError extends Error {
  readonly name = "EstimateCalculationError";
  readonly code = "PROVENANCE_CONFLICT";
}

export function calculateEstimate(estimate: Estimate): EstimateCalculation {
  estimate.lines.forEach((line) => {
    assertExactCostMethod(line.cost);
  });
  const lines = estimate.lines.map(calculateLine);
  const subtotalWon = lines.reduce(
    (sum, line) => sum.plus(line.subtotalWon),
    new Decimal("0")
  );
  return {
    estimateId: estimate.id,
    revision: estimate.revision,
    lines,
    subtotalWon,
    total: calculateProfileTotal({
      subtotalWon,
      feePolicy: estimate.profile.feePolicy
    })
  };
}

function assertExactCostMethod(cost: EstimateLine["cost"]): void {
  switch (cost.kind) {
    case "direct":
      assertExactKeys(cost, ["kind", "provenance"]);
      break;
    case "three_company_min":
      assertExactKeys(cost, ["kind", "quotes"]);
      break;
    case "market_price":
    case "standard_quantity":
      assertExactKeys(cost, ["kind", "provenance", "rateContext"]);
      break;
    default:
      assertNever(cost);
  }
}

function assertExactKeys(value: object, expected: readonly string[]): void {
  const actual = Object.keys(value);
  if (
    actual.length !== expected.length ||
    expected.some((key) => !actual.includes(key))
  ) {
    throw new EstimateCalculationError("PROVENANCE_CONFLICT");
  }
}

function calculateLine(line: EstimateLine): LineCalculation {
  switch (line.cost.kind) {
    case "direct": {
      const unitCostWon = line.cost.provenance.unitPriceWon;
      return lineResult(line, unitCostWon, line.cost.provenance);
    }
    case "three_company_min": {
      const [a, b, c] = line.cost.quotes;
      const candidates = [
        { slot: a.slot, ...quoteSourceIdentity(a.provenance) },
        { slot: b.slot, ...quoteSourceIdentity(b.provenance) },
        { slot: c.slot, ...quoteSourceIdentity(c.provenance) }
      ] as const;
      const selected = selectThreeCompanyMinimum(candidates);
      const provenance = ThreeCompanyMinimumProvenanceSchema.parse({
        kind: "three_company_min",
        selectedSlot: selected.slot,
        selectedQuoteId: selected.quoteId,
        candidates: candidates.map((candidate) => ({
          ...candidate,
          unitPriceWon: candidate.unitPriceWon.toFixed(0)
        }))
      });
      return lineResult(line, selected.unitPriceWon, provenance);
    }
    case "market_price":
      return lineResult(
        line,
        line.cost.provenance.unitPriceWon,
        line.cost.provenance
      );
    case "standard_quantity": {
      const unitCostWon = line.cost.provenance.coefficients.reduce(
        (sum, item) => sum.plus(item.coefficient.times(item.dailyWageWon)),
        new Decimal("0")
      );
      return lineResult(line, unitCostWon, line.cost.provenance);
    }
    default:
      return assertNever(line.cost);
  }
}

function lineResult(
  line: EstimateLine,
  unitCostWon: Decimal,
  provenance: Provenance
): LineCalculation {
  return {
    id: line.id,
    role: line.role,
    unitCostWon,
    subtotalWon: unitCostWon.times(line.quantity),
    provenance
  };
}

function quoteCandidate(slot: "A" | "B" | "C") {
  return z
    .strictObject({
      slot: z.literal(slot),
      provenance: QuoteSourceSchema
    })
    .readonly();
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected cost method: ${String(value)}`);
}
