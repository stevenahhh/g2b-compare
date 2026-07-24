import Decimal from "decimal.js";
import { z } from "zod";
import {
  type MarketPriceRow,
  MarketPriceRowSchema,
  type ProductivityRow,
  ProductivityRowSchema,
  type WageRow,
  WageRowSchema
} from "./schemas.js";

const QuantitySchema = z
  .string()
  .regex(/^(?:0|[1-9]\d*)(?:\.\d+)?$/u)
  .refine((value) => new Decimal(value).greaterThan(0));

const MarketPriceInputSchema = z
  .strictObject({
    kind: z.literal("market_price"),
    quantity: QuantitySchema,
    marketPrice: MarketPriceRowSchema
  })
  .readonly();

const StandardQuantityInputSchema = z
  .strictObject({
    kind: z.literal("standard_quantity"),
    quantity: QuantitySchema,
    productivity: ProductivityRowSchema,
    wages: z.array(WageRowSchema).readonly()
  })
  .readonly();

const UserQuoteInputSchema = z
  .strictObject({
    kind: z.literal("user_quote"),
    quantity: QuantitySchema,
    unitPriceWon: z.number().int().positive()
  })
  .readonly();

export const OfficialPricingInputSchema = z.discriminatedUnion("kind", [
  MarketPriceInputSchema,
  StandardQuantityInputSchema,
  UserQuoteInputSchema
]);

type OfficialPricingInput = z.output<typeof OfficialPricingInputSchema>;

export type OfficialSource = {
  readonly rowIdentity: string;
  readonly sourceId: string;
  readonly sourceUrl: string;
  readonly sourcePdfSha256: string;
  readonly sourcePdfPages: readonly number[];
  readonly effectiveFrom: string;
  readonly licenseId: string;
};

export type OfficialPriceCalculation = {
  readonly method: OfficialPricingInput["kind"];
  readonly marketPriceContributionWon: Decimal;
  readonly standardQuantityContributionWon: Decimal;
  readonly totalWon: Decimal;
  readonly officialSources: readonly OfficialSource[];
};

export class PricingError extends Error {
  readonly name = "PricingError";

  constructor(
    readonly code:
      | "OFFICIAL_WAGE_NOT_FOUND"
      | "PRICING_INPUT_INVALID"
      | "PRICING_METHOD_CONFLICT",
    message: string
  ) {
    super(message);
  }
}

export function calculateOfficialPrice(
  input: unknown
): OfficialPriceCalculation {
  if (
    input !== null &&
    typeof input === "object" &&
    "marketPrice" in input &&
    ("productivity" in input || "wages" in input)
  ) {
    throw new PricingError(
      "PRICING_METHOD_CONFLICT",
      "market price and standard quantity cannot be combined"
    );
  }
  const parsed = OfficialPricingInputSchema.safeParse(input);
  if (!parsed.success) {
    throw new PricingError("PRICING_INPUT_INVALID", "invalid pricing input");
  }
  switch (parsed.data.kind) {
    case "market_price":
      return marketPriceCalculation(parsed.data);
    case "standard_quantity":
      return standardQuantityCalculation(parsed.data);
    case "user_quote":
      return userQuoteCalculation(parsed.data);
    default:
      return assertNever(parsed.data);
  }
}

function marketPriceCalculation(
  input: z.output<typeof MarketPriceInputSchema>
): OfficialPriceCalculation {
  const contribution = new Decimal(input.marketPrice.unit_price_krw).times(
    input.quantity
  );
  return Object.freeze({
    method: input.kind,
    marketPriceContributionWon: contribution,
    standardQuantityContributionWon: new Decimal(0),
    totalWon: contribution,
    officialSources: Object.freeze([marketSource(input.marketPrice)])
  });
}

function standardQuantityCalculation(
  input: z.output<typeof StandardQuantityInputSchema>
): OfficialPriceCalculation {
  const wages = new Map(input.wages.map((wage) => [wage.job_code, wage]));
  const selectedWages: WageRow[] = [];
  const unitPriceWon = Object.entries(
    input.productivity.coefficients_by_job_code
  ).reduce((sum, [jobCode, coefficient]) => {
    const wage = wages.get(jobCode);
    if (wage === undefined) {
      throw new PricingError(
        "OFFICIAL_WAGE_NOT_FOUND",
        `official wage ${jobCode} is missing`
      );
    }
    selectedWages.push(wage);
    return sum.plus(new Decimal(coefficient).times(wage.daily_wage_krw));
  }, new Decimal(0));
  const contribution = unitPriceWon.times(input.quantity);
  return Object.freeze({
    method: input.kind,
    marketPriceContributionWon: new Decimal(0),
    standardQuantityContributionWon: contribution,
    totalWon: contribution,
    officialSources: Object.freeze([
      productivitySource(input.productivity),
      ...selectedWages.map(wageSource)
    ])
  });
}

function userQuoteCalculation(
  input: z.output<typeof UserQuoteInputSchema>
): OfficialPriceCalculation {
  const totalWon = new Decimal(input.unitPriceWon).times(input.quantity);
  return Object.freeze({
    method: input.kind,
    marketPriceContributionWon: new Decimal(0),
    standardQuantityContributionWon: new Decimal(0),
    totalWon,
    officialSources: Object.freeze([])
  });
}

function marketSource(row: MarketPriceRow): OfficialSource {
  return Object.freeze({
    rowIdentity: row.work_code,
    sourceId: row.source_id,
    sourceUrl: row.source_url,
    sourcePdfSha256: row.source_pdf_sha256,
    sourcePdfPages: Object.freeze([row.source_pdf_page]),
    effectiveFrom: row.effective_from,
    licenseId: row.license_id
  });
}

function productivitySource(row: ProductivityRow): OfficialSource {
  return Object.freeze({
    rowIdentity: `${row.standard_item}|${row.task}|${row.specification}|${row.unit}`,
    sourceId: row.source_id,
    sourceUrl: row.source_url,
    sourcePdfSha256: row.source_pdf_sha256,
    sourcePdfPages: row.source_pdf_pages,
    effectiveFrom: row.effective_from,
    licenseId: row.license_id
  });
}

function wageSource(row: WageRow): OfficialSource {
  return Object.freeze({
    rowIdentity: row.job_code,
    sourceId: row.source_id,
    sourceUrl: row.source_url,
    sourcePdfSha256: row.source_pdf_sha256,
    sourcePdfPages: row.source_pdf_pages,
    effectiveFrom: row.effective_from,
    licenseId: row.license_id
  });
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected pricing method: ${String(value)}`);
}
