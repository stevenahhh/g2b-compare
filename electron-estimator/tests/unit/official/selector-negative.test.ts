import { expect, test } from "vitest";
import { selectKoreaNetCandidate } from "../../../src/official/selector.js";
import {
  COMPETITOR_OBSERVATION,
  KOREANET_OBSERVATION,
  SELECTION_TARGET
} from "./fixtures.js";

test.each([
  ["payload hash", { source_payload_sha256: undefined }],
  ["location", { supplier_location_evidence: undefined }],
  ["service", { service_area_evidence: undefined }]
])(
  "Given KoreaNet is missing %s evidence When selection runs Then it fails closed",
  (_caseName, change) => {
    // Given
    const request = {
      ...SELECTION_TARGET,
      candidates: [
        { ...KOREANET_OBSERVATION, ...change },
        COMPETITOR_OBSERVATION
      ]
    };

    // When
    const result = selectKoreaNetCandidate(request);

    // Then
    expect(result).toMatchObject({
      kind: "not_selected",
      autoSelected: false,
      reason: "SOURCE_EVIDENCE_INCOMPLETE"
    });
  }
);

test("Given a second KoreaNet candidate lacks location evidence When selection runs Then the entire KoreaNet selection fails closed", () => {
  // Given
  const request = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      {
        ...KOREANET_OBSERVATION,
        observation_id: "koreanet-incomplete",
        supplier_location_evidence: undefined
      },
      COMPETITOR_OBSERVATION
    ]
  };

  // When
  const result = selectKoreaNetCandidate(request);

  // Then
  expect(result).toMatchObject({
    kind: "not_selected",
    autoSelected: false,
    reason: "SOURCE_EVIDENCE_INCOMPLETE"
  });
});

test("Given only location and service statements change When ranked Then price and selection are unchanged", () => {
  // Given
  const baseline = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      { ...COMPETITOR_OBSERVATION, unit_price_won: 999 }
    ]
  };
  const changed = {
    ...baseline,
    candidates: [
      {
        ...KOREANET_OBSERVATION,
        supplier_location_evidence: {
          ...KOREANET_OBSERVATION.supplier_location_evidence,
          statement: "Changed location wording"
        },
        service_area_evidence: {
          ...KOREANET_OBSERVATION.service_area_evidence,
          statement: "Changed service wording"
        }
      },
      baseline.candidates[1]
    ]
  };

  // When
  const before = selectKoreaNetCandidate(baseline);
  const after = selectKoreaNetCandidate(changed);

  // Then
  expect(after.reason).toBe(before.reason);
  expect(after.lowestUnitPriceWon).toBe(before.lowestUnitPriceWon);
  expect(after.selected).toEqual(before.selected);
});

test("Given KoreaNet is tied lowest When only location and service statements change Then selection identity stays KoreaNet", () => {
  // Given
  const baseline = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      { ...COMPETITOR_OBSERVATION, unit_price_won: 1000 }
    ]
  };
  const changed = {
    ...baseline,
    candidates: [
      {
        ...KOREANET_OBSERVATION,
        supplier_location_evidence: {
          ...KOREANET_OBSERVATION.supplier_location_evidence,
          statement: "Different location statement"
        },
        service_area_evidence: {
          ...KOREANET_OBSERVATION.service_area_evidence,
          statement: "Different service statement"
        }
      },
      baseline.candidates[1]
    ]
  };

  // When
  const before = selectKoreaNetCandidate(baseline);
  const after = selectKoreaNetCandidate(changed);

  // Then
  expect(after.reason).toBe("KOREANET_TIED_LOWEST");
  expect(after.reason).toBe(before.reason);
  expect(after.selected?.observation_id).toBe(
    before.selected?.observation_id
  );
});
