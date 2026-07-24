import { expect, test } from "vitest";
import {
  calculateProfileTotal,
  parseNonnegativeDecimal,
  parsePositiveWon,
  parseRate
} from "../../../src/domain/money.js";
import { DirectProvenanceSchema, serializeProvenance } from "../../../src/domain/provenance.js";
import { DIRECT_SOURCE } from "./fixtures.js";

test("manual domain oracle emits B C and authentic provenance", () => {
  // Given
  const feePolicy = {
    kind: "total_up",
    rate: parseRate("0.0054"),
    incrementWon: parsePositiveWon("1000")
  } as const;
  const provenance = DirectProvenanceSchema.parse(DIRECT_SOURCE);

  // When
  const b = calculateProfileTotal({
    subtotalWon: parseNonnegativeDecimal("20174460"),
    feePolicy
  });
  const c = calculateProfileTotal({
    subtotalWon: parseNonnegativeDecimal("65499660"),
    feePolicy
  });
  const output = {
    B: {
      subtotalWon: "20174460",
      rawFeeWon: b.rawFeeWon.toString(),
      totalWon: b.totalWon.toFixed(0)
    },
    C: {
      subtotalWon: "65499660",
      rawFeeWon: c.rawFeeWon.toString(),
      totalWon: c.totalWon.toFixed(0)
    },
    provenance: JSON.parse(serializeProvenance(provenance))
  };
  console.log(JSON.stringify(output));

  // Then
  expect(output.B).toEqual({
    subtotalWon: "20174460",
    rawFeeWon: "108942.084",
    totalWon: "20284000"
  });
  expect(output.C).toEqual({
    subtotalWon: "65499660",
    rawFeeWon: "353698.164",
    totalWon: "65854000"
  });
  expect(output.provenance.kind).toBe("direct");
});
