import { expect, test } from "vitest";
import { calculateEstimate } from "../../../src/domain/estimate.js";
import { parseEstimateInput } from "../../../src/domain/validation.js";
import {
  BASE_ESTIMATE,
  BASE_LINE,
  MARKET_PRICE_SOURCE,
  PRODUCTIVITY_SOURCE,
  RATE_CONTEXT
} from "./fixtures.js";

test("Given an unbound option When the estimate is calculated Then its role and cost are preserved", () => {
  // Given
  const estimate = parseEstimateInput({
    ...BASE_ESTIMATE,
    lines: [
      BASE_LINE,
      {
        ...BASE_LINE,
        id: "line-option",
        role: { kind: "unbound_option" },
        quantity: "1"
      }
    ]
  });

  // When
  const result = calculateEstimate(estimate);

  // Then
  expect(result.lines).toHaveLength(2);
  expect(result.lines[1]?.role.kind).toBe("unbound_option");
  expect(result.subtotalWon.toString()).toBe("4500");
  expect(result.total.totalWon.toFixed(0)).toBe("5000");
});

test("Given official market price evidence When line cost is calculated Then exact unit evidence is used", () => {
  // Given
  const estimate = parseEstimateInput({
    ...BASE_ESTIMATE,
    lines: [
      {
        id: "line-market",
        role: { kind: "main" },
        itemName: "광섬유케이블",
        specification: MARKET_PRICE_SOURCE.specification,
        unit: MARKET_PRICE_SOURCE.unit,
        quantity: "2",
        cost: {
          kind: "market_price",
          provenance: MARKET_PRICE_SOURCE,
          rateContext: RATE_CONTEXT
        }
      }
    ]
  });

  // When
  const result = calculateEstimate(estimate);

  // Then
  expect(result.lines[0]?.unitCostWon.toString()).toBe("6251");
  expect(result.subtotalWon.toString()).toBe("12502");
});

test("Given official productivity and wage evidence When line cost is calculated Then Decimal coefficients stay exact", () => {
  // Given
  const estimate = parseEstimateInput({
    ...BASE_ESTIMATE,
    lines: [
      {
        id: "line-productivity",
        role: { kind: "main" },
        itemName: "카메라 설치",
        specification: PRODUCTIVITY_SOURCE.specification,
        unit: PRODUCTIVITY_SOURCE.unit,
        quantity: "2",
        cost: {
          kind: "standard_quantity",
          provenance: PRODUCTIVITY_SOURCE,
          rateContext: {
            ...RATE_CONTEXT,
            pricingMethod: "official-standard-quantity",
            suppliedMaterials: "excluded"
          }
        }
      }
    ]
  });

  // When
  const result = calculateEstimate(estimate);

  // Then
  expect(result.lines[0]?.unitCostWon.toString()).toBe("1250");
  expect(result.subtotalWon.toString()).toBe("2500");
});
