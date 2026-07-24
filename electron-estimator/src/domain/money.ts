import Decimal from "decimal.js";
import { z } from "zod";

const DECIMAL_LEXEME = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const POSITIVE_WON_LEXEME = /^[1-9]\d*$/;

const DecimalLexemeSchema = z
  .string()
  .regex(DECIMAL_LEXEME, { message: "INVALID_DECIMAL" })
  .transform((value) => new Decimal(value));

export const NonnegativeDecimalSchema = DecimalLexemeSchema.refine(
  (value) => value.isFinite() && value.greaterThanOrEqualTo(0),
  { message: "INVALID_DECIMAL" }
);

export const QuantitySchema = DecimalLexemeSchema.refine(
  (value) => value.isFinite() && value.greaterThan(0),
  { message: "NEGATIVE_QUANTITY" }
);

export const PositiveDecimalSchema = DecimalLexemeSchema.refine(
  (value) => value.isFinite() && value.greaterThan(0),
  { message: "INVALID_DECIMAL" }
);

export const RateSchema = DecimalLexemeSchema.refine(
  (value) => value.isFinite() && value.greaterThanOrEqualTo(0),
  { message: "INVALID_DECIMAL" }
);

export const PositiveWonSchema = z
  .string()
  .regex(POSITIVE_WON_LEXEME, { message: "INVALID_DECIMAL" })
  .transform((value) => new Decimal(value));

const FeeUpPolicySchema = z
  .strictObject({
    kind: z.literal("fee_up"),
    rate: RateSchema,
    incrementWon: PositiveWonSchema
  })
  .readonly();

const TotalUpPolicySchema = z
  .strictObject({
    kind: z.literal("total_up"),
    rate: RateSchema,
    incrementWon: PositiveWonSchema
  })
  .readonly();

export const FeePolicySchema = z.discriminatedUnion("kind", [
  FeeUpPolicySchema,
  TotalUpPolicySchema
]);

export type FeePolicy = z.output<typeof FeePolicySchema>;

export type QuoteCandidate = {
  readonly slot: "A" | "B" | "C";
  readonly quoteId: string;
  readonly unitPriceWon: Decimal;
};

export type FeeUpTotal = {
  readonly kind: "fee_up";
  readonly subtotalWon: Decimal;
  readonly rawFeeWon: Decimal;
  readonly roundedFeeWon: Decimal;
  readonly totalWon: Decimal;
};

export type TotalUpTotal = {
  readonly kind: "total_up";
  readonly subtotalWon: Decimal;
  readonly rawFeeWon: Decimal;
  readonly unroundedTotalWon: Decimal;
  readonly totalWon: Decimal;
};

export type ProfileTotal = FeeUpTotal | TotalUpTotal;

export function parseNonnegativeDecimal(value: unknown): Decimal {
  return NonnegativeDecimalSchema.parse(value);
}

export function parsePositiveWon(value: unknown): Decimal {
  return PositiveWonSchema.parse(value);
}

export function parseRate(value: unknown): Decimal {
  return RateSchema.parse(value);
}

export function selectThreeCompanyMinimum(
  quotes: readonly [QuoteCandidate, QuoteCandidate, QuoteCandidate]
): QuoteCandidate {
  const [first, ...rest] = quotes;
  return rest.reduce(
    (selected, candidate) =>
      candidate.unitPriceWon.lessThan(selected.unitPriceWon) ? candidate : selected,
    first
  );
}

export function calculateProfileTotal(input: {
  readonly subtotalWon: Decimal;
  readonly feePolicy: FeePolicy;
}): ProfileTotal {
  const rawFeeWon = input.subtotalWon.times(input.feePolicy.rate);
  switch (input.feePolicy.kind) {
    case "fee_up": {
      const roundedFeeWon = roundUp(rawFeeWon, input.feePolicy.incrementWon);
      return {
        kind: "fee_up",
        subtotalWon: input.subtotalWon,
        rawFeeWon,
        roundedFeeWon,
        totalWon: input.subtotalWon.plus(roundedFeeWon)
      };
    }
    case "total_up": {
      const unroundedTotalWon = input.subtotalWon.plus(rawFeeWon);
      return {
        kind: "total_up",
        subtotalWon: input.subtotalWon,
        rawFeeWon,
        unroundedTotalWon,
        totalWon: roundUp(unroundedTotalWon, input.feePolicy.incrementWon)
      };
    }
    default:
      return assertNever(input.feePolicy);
  }
}

function roundUp(value: Decimal, increment: Decimal): Decimal {
  return value.dividedBy(increment).ceil().times(increment);
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected fee policy: ${String(value)}`);
}
