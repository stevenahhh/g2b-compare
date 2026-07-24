import { expect, test } from "vitest";
import {
  calculateOfficialPrice,
  OfficialPricingInputSchema,
  type PricingError
} from "../../../src/official/pricing.js";
import { loadOfficialRepository } from "../../../src/official/repository.js";

test("Given market pricing When calculated Then standard-quantity contribution is zero", async () => {
  // Given
  const repository = await loadOfficialRepository();
  const marketPrice = repository.marketPrices[0];

  // When
  const result = calculateOfficialPrice({
    kind: "market_price",
    quantity: "2",
    marketPrice
  });

  // Then
  expect(result.marketPriceContributionWon.toFixed(0)).toBe("12502");
  expect(result.standardQuantityContributionWon.toFixed(0)).toBe("0");
  expect(result.totalWon.toFixed(0)).toBe("12502");
  expect(result.officialSources).toHaveLength(1);
});

test("Given standard productivity and wages When calculated Then market contribution is zero", async () => {
  // Given
  const repository = await loadOfficialRepository();
  const productivity = repository.productivity[0];

  // When
  const result = calculateOfficialPrice({
    kind: "standard_quantity",
    quantity: "2",
    productivity,
    wages: repository.wages
  });

  // Then
  expect(result.marketPriceContributionWon.toFixed(0)).toBe("0");
  expect(result.standardQuantityContributionWon.greaterThan(0)).toBe(true);
  expect(result.totalWon.equals(result.standardQuantityContributionWon)).toBe(true);
  expect(result.officialSources.length).toBeGreaterThan(1);
});

test("Given a user quote When calculated Then official sources and official or latest labels are absent", () => {
  // Given / When
  const result = calculateOfficialPrice({
    kind: "user_quote",
    quantity: "2",
    unitPriceWon: 500
  });

  // Then
  expect(result.totalWon.toFixed(0)).toBe("1000");
  expect(result.officialSources).toEqual([]);
  expect("officialLabel" in result).toBe(false);
  expect("latestLabel" in result).toBe(false);
});

test("Given both market and standard fields When parsed or calculated Then it rejects double counting", async () => {
  // Given
  const repository = await loadOfficialRepository();
  const payload = {
    kind: "market_price",
    quantity: "1",
    marketPrice: repository.marketPrices[0],
    productivity: repository.productivity[0],
    wages: repository.wages
  };

  // When
  const parsed = OfficialPricingInputSchema.safeParse(payload);

  // Then
  expect(parsed.success).toBe(false);
  expect(() => calculateOfficialPrice(payload)).toThrowError(
    expect.objectContaining({
      code: "PRICING_METHOD_CONFLICT"
    } satisfies Partial<PricingError>)
  );
});
