import { expect, test } from "vitest";
import { calculateEstimate } from "../../../src/domain/estimate.js";
import {
  serializeProvenance,
  ThreeCompanyMinimumProvenanceSchema
} from "../../../src/domain/provenance.js";
import { parseEstimateInput } from "../../../src/domain/validation.js";
import {
  BASE_ESTIMATE,
  BASE_LINE,
  USER_QUOTE_A,
  USER_QUOTE_B,
  USER_QUOTE_C
} from "./fixtures.js";

test("Given three comparable quotes When calculated Then selected provenance is structured and reusable only as output", () => {
  // Given
  const estimate = parseEstimateInput({
    ...BASE_ESTIMATE,
    lines: [
      {
        ...BASE_LINE,
        cost: {
          kind: "three_company_min",
          quotes: [
            { slot: "A", provenance: USER_QUOTE_A },
            { slot: "B", provenance: USER_QUOTE_B },
            { slot: "C", provenance: USER_QUOTE_C }
          ]
        }
      }
    ]
  });

  // When
  const result = calculateEstimate(estimate);
  const selected = result.lines[0]?.provenance;
  const serialized = selected === undefined ? "" : serializeProvenance(selected);
  const reparsed = ThreeCompanyMinimumProvenanceSchema.parse(JSON.parse(serialized));

  // Then
  expect(reparsed.kind).toBe("three_company_min");
  expect(reparsed.selectedSlot).toBe("A");
  expect(reparsed.candidates.map((candidate) => candidate.slot)).toEqual(["A", "B", "C"]);
  expect(reparsed.candidates.map((candidate) => candidate.unitPriceWon.toString())).toEqual([
    "1000",
    "1000",
    "1200"
  ]);
});
