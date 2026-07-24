import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { z } from "zod";
import {
  calculateEstimate,
  EstimateProfileSchema
} from "../../../src/domain/estimate.js";
import {
  calculateProfileTotal,
  parseNonnegativeDecimal
} from "../../../src/domain/money.js";
import {
  DomainValidationError,
  parseEstimateInput
} from "../../../src/domain/validation.js";
import {
  BASE_ESTIMATE,
  BASE_LINE,
  MARKET_PRICE_SOURCE,
  PROFILE_A,
  PROFILE_B,
  PROFILE_C,
  RATE_CONTEXT,
  SHA_C
} from "./fixtures.js";

function expectValidationCode(input: unknown, code: DomainValidationError["code"]): void {
  try {
    parseEstimateInput(input);
  } catch (error) {
    expect(error).toBeInstanceOf(DomainValidationError);
    if (error instanceof DomainValidationError) {
      expect(error.code).toBe(code);
      return;
    }
    throw error;
  }
  expect.fail(`Expected ${code}`);
}

function marketEstimate() {
  return {
    ...BASE_ESTIMATE,
    lines: [
      {
        id: "line-market",
        role: { kind: "main" },
        itemName: "광섬유케이블",
        specification: MARKET_PRICE_SOURCE.specification,
        unit: MARKET_PRICE_SOURCE.unit,
        quantity: "1",
        cost: {
          kind: "market_price",
          provenance: MARKET_PRICE_SOURCE,
          rateContext: RATE_CONTEXT
        }
      }
    ]
  };
}

test("Given a parsed market estimate with injected productivity fields When calculated Then exact variant enforcement rejects it", () => {
  // Given
  const parsed = parseEstimateInput(marketEstimate());
  const blended = {
    ...parsed,
    lines: parsed.lines.map((line) => ({
      ...line,
      cost: { ...line.cost, coefficients: [] }
    }))
  };

  // When / Then
  expect(() => calculateEstimate(blended)).toThrow();
});

test("Given provenance and context share the same stale official revision When parsed Then Task 3 pins reject both", () => {
  // Given
  const stale = marketEstimate();
  const input = {
    ...stale,
    lines: stale.lines.map((line) => ({
      ...line,
      cost: {
        ...line.cost,
        provenance: {
          ...line.cost.provenance,
          datasetVersion: "stale-dataset",
          sourceManifestSha256: SHA_C
        },
        rateContext: {
          ...line.cost.rateContext,
          datasetVersion: "stale-dataset",
          sourceManifestSha256: SHA_C
        }
      }
    }))
  };

  // When / Then
  expectValidationCode(input, "STALE_PROVENANCE");
});

test("Given B profile with substituted fee rate or rounding When parsed Then native policy rejects it", () => {
  // Given
  const substitutedRate = {
    ...PROFILE_B,
    feePolicy: { ...PROFILE_B.feePolicy, rate: "0.9" }
  };
  const substitutedRounding = {
    ...PROFILE_B,
    feePolicy: {
      ...PROFILE_B.feePolicy,
      kind: "fee_up"
    }
  };

  // When
  const rateResult = EstimateProfileSchema.safeParse(substitutedRate);
  const roundingResult = EstimateProfileSchema.safeParse(substitutedRounding);

  // Then
  expect(rateResult.success).toBe(false);
  expect(roundingResult.success).toBe(false);
});

test.each([
  ["A", PROFILE_A],
  ["B", PROFILE_B],
  ["C", PROFILE_C]
])(
  "Given profile %s with an arbitrary 64-character revision When parsed Then its source revision is rejected",
  (_profileId, profile) => {
    // Given
    const input = { ...profile, revision: "f".repeat(64) };

    // When
    const result = EstimateProfileSchema.safeParse(input);

    // Then
    expect(result.success).toBe(false);
  }
);

test("Given a bound option whose parent is absent When parsed Then parent validation rejects it", () => {
  // Given
  const input = {
    ...BASE_ESTIMATE,
    lines: [
      BASE_LINE,
      {
        ...BASE_LINE,
        id: "line-option",
        role: { kind: "bound_option", parentLineId: "missing-main" }
      }
    ]
  };

  // When / Then
  expectValidationCode(input, "INVALID_OPTION_PARENT");
});

test("Given the project typecheck config When read Then domain and shared contracts are included", async () => {
  // Given
  const text = await readFile(resolve(process.cwd(), "tsconfig.json"), "utf8");
  const config = z
    .strictObject({ include: z.array(z.string()) })
    .passthrough()
    .parse(JSON.parse(text));

  // When / Then
  expect(config.include).toContain("src/domain/**/*.ts");
  expect(config.include).toContain("src/shared/**/*.ts");
});

test("Given native A B C profiles When totals are calculated Then all manifest oracles remain exact", () => {
  // Given
  const cases = [
    { profile: PROFILE_A, subtotalWon: "38938530", totalWon: "39149530" },
    { profile: PROFILE_B, subtotalWon: "20174460", totalWon: "20284000" },
    { profile: PROFILE_C, subtotalWon: "65499660", totalWon: "65854000" }
  ];

  // When
  const totals = cases.map((item) => {
    const profile = EstimateProfileSchema.parse(item.profile);
    return calculateProfileTotal({
      subtotalWon: parseNonnegativeDecimal(item.subtotalWon),
      feePolicy: profile.feePolicy
    }).totalWon.toFixed(0);
  });

  // Then
  expect(totals).toEqual(cases.map((item) => item.totalWon));
});
