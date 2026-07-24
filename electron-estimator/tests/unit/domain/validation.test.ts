import { expect, test } from "vitest";
import {
  DomainValidationError,
  parseEstimateInput
} from "../../../src/domain/validation.js";
import {
  BASE_ESTIMATE,
  BASE_LINE,
  MARKET_PRICE_SOURCE,
  PROFILE_B,
  RATE_CONTEXT,
  SHA_B
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

test("rejects invalid financial inputs", () => {
  // Given
  const negativeQuantity = {
    ...BASE_ESTIMATE,
    lines: [{ ...BASE_LINE, quantity: "-1" }]
  };
  const overCapacity = {
    ...BASE_ESTIMATE,
    lines: Array.from({ length: 10 }, (_, index) => ({
      ...BASE_LINE,
      id: `line-${index}`
    }))
  };
  const mixedProvenance = {
    ...BASE_ESTIMATE,
    lines: [
      {
        ...BASE_LINE,
        cost: {
          kind: "direct",
          provenance: MARKET_PRICE_SOURCE
        }
      }
    ]
  };

  // When / Then
  expectValidationCode(negativeQuantity, "NEGATIVE_QUANTITY");
  expectValidationCode(overCapacity, "PROFILE_CAPACITY_EXCEEDED");
  expectValidationCode(mixedProvenance, "PROVENANCE_CONFLICT");
});

test.each(["", "../estimate", "has space", "한글-id", "x".repeat(65)])(
  "rejects unsafe estimate ID %s",
  (id) => {
    // Given / When / Then
    expectValidationCode({ ...BASE_ESTIMATE, id }, "INVALID_ID");
  }
);

test.each(["1e2", " 2", "+2", "0x2", "2_0", "NaN", "Infinity"])(
  "rejects malformed quantity %s",
  (quantity) => {
    // Given / When / Then
    expectValidationCode(
      { ...BASE_ESTIMATE, lines: [{ ...BASE_LINE, quantity }] },
      "INVALID_DECIMAL"
    );
  }
);

test("Given an official source from a stale manifest When parsed Then stale provenance is rejected", () => {
  // Given
  const stale = {
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
          rateContext: {
            ...RATE_CONTEXT,
            sourceManifestSha256: SHA_B
          }
        }
      }
    ]
  };

  // When / Then
  expectValidationCode(stale, "STALE_PROVENANCE");
});

test("Given an official rate without complete context When parsed Then it is rejected", () => {
  // Given
  const missingRateContext = {
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
          provenance: MARKET_PRICE_SOURCE
        }
      }
    ]
  };

  // When / Then
  expectValidationCode(missingRateContext, "RATE_CONTEXT_REQUIRED");
});

test("Given market and productivity fields in one method When parsed Then the conflict is rejected", () => {
  // Given
  const blended = {
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
          rateContext: RATE_CONTEXT,
          coefficients: []
        }
      }
    ]
  };

  // When / Then
  expectValidationCode(blended, "PROVENANCE_CONFLICT");
});
