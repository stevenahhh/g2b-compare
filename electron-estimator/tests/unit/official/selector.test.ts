import { expect, test } from "vitest";
import { SourcedProductObservationSchema } from "../../../src/official/schemas.js";
import { selectKoreaNetCandidate } from "../../../src/official/selector.js";
import {
  COMPETITOR_OBSERVATION,
  KOREANET_OBSERVATION,
  SELECTION_TARGET
} from "./fixtures.js";

test("Given a canonical sourced observation When runtime parsing runs Then selection evidence is accepted", () => {
  const result = SourcedProductObservationSchema.safeParse(
    KOREANET_OBSERVATION
  );

  expect(result.success).toBe(true);
});

test("Given an invented top-level comparison group When runtime parsing runs Then the unknown field is rejected", () => {
  const result = SourcedProductObservationSchema.safeParse({
    ...KOREANET_OBSERVATION,
    comparison_group_id: "cctv-4mp-camera"
  });

  expect(result.success).toBe(false);
  if (result.success) {
    expect.fail("Expected strict canonical observation rejection");
  }
  expect(result.error.issues).toContainEqual(
    expect.objectContaining({
      code: "unrecognized_keys",
      keys: ["comparison_group_id"]
    })
  );
});

test.each([
  ["lowest", 1100, "KOREANET_LOWEST"],
  ["tied", 1000, "KOREANET_TIED_LOWEST"]
])(
  "Given KoreaNet is %s When authentic comparable candidates are ranked Then KoreaNet is auto-selected",
  (_caseName, competitorPrice, expectedReason) => {
    // Given
    const request = {
      ...SELECTION_TARGET,
      candidates: [
        KOREANET_OBSERVATION,
        { ...COMPETITOR_OBSERVATION, unit_price_won: competitorPrice }
      ]
    };

    // When
    const result = selectKoreaNetCandidate(request);

    // Then
    expect(result).toMatchObject({
      kind: "selected",
      autoSelected: true,
      reason: expectedReason,
      selected: {
        product_id: "12345678",
        source_url: KOREANET_OBSERVATION.source_url,
        api_operation: "getProductInfo",
        observed_at: KOREANET_OBSERVATION.observed_at,
        source_payload_sha256: KOREANET_OBSERVATION.source_payload_sha256,
        supplier_location_evidence:
          KOREANET_OBSERVATION.supplier_location_evidence,
        service_area_evidence: KOREANET_OBSERVATION.service_area_evidence
      }
    });
  }
);

test("Given an authentic candidate is one won cheaper When ranked Then location cannot override price", () => {
  // Given
  const request = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      {
        ...COMPETITOR_OBSERVATION,
        unit_price_won: 999,
        supplier_name: "Remote Authentic Supplier"
      }
    ]
  };

  // When
  const result = selectKoreaNetCandidate(request);

  // Then
  expect(result).toMatchObject({
    kind: "not_selected",
    autoSelected: false,
    reason: "LOWER_AUTHENTIC_CANDIDATE",
    lowestUnitPriceWon: 999
  });
});

test.each([
  ["specification", { spec_snapshot: "CCTV 2MP" }, "SPECIFICATION_MISMATCH"],
  ["unit", { unit: "SET" }, "UNIT_MISMATCH"]
])(
  "Given KoreaNet has a %s mismatch When ranked Then it is not comparable",
  (_caseName, change, reason) => {
    // Given
    const request = {
      ...SELECTION_TARGET,
      candidates: [{ ...KOREANET_OBSERVATION, ...change }, COMPETITOR_OBSERVATION]
    };

    // When
    const result = selectKoreaNetCandidate(request);

    // Then
    expect(result).toMatchObject({
      kind: "not_selected",
      autoSelected: false,
      reason
    });
  }
);

test("Given a cheaper candidate lacks authentic payload evidence When ranked Then it is excluded", () => {
  // Given
  const request = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      {
        ...COMPETITOR_OBSERVATION,
        unit_price_won: 1,
        authenticity: undefined
      },
      { ...COMPETITOR_OBSERVATION, observation_id: "competitor-b" }
    ]
  };

  // When
  const result = selectKoreaNetCandidate(request);

  // Then
  expect(result).toMatchObject({
    kind: "selected",
    reason: "KOREANET_LOWEST"
  });
  expect(result.comparableCandidates).toHaveLength(2);
});

test("Given only KoreaNet is comparable When ranked Then automatic selection fails closed", () => {
  // Given
  const request = {
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      { ...COMPETITOR_OBSERVATION, unit: "SET" }
    ]
  };

  // When
  const result = selectKoreaNetCandidate(request);

  // Then
  expect(result).toMatchObject({
    kind: "not_selected",
    autoSelected: false,
    reason: "NO_COMPARABLE_CANDIDATE"
  });
});

test("Given an unrelated authentic one-won group When ranked Then only the requested equivalent item group competes", () => {
  const result = selectKoreaNetCandidate({
    ...SELECTION_TARGET,
    candidates: [
      KOREANET_OBSERVATION,
      {
        ...COMPETITOR_OBSERVATION,
        observation_id: "unrelated-one-won",
        selection_evidence: {
          ...COMPETITOR_OBSERVATION.selection_evidence,
          comparison_group: "unrelated-network-switch"
        },
        unit_price_won: 1
      },
      COMPETITOR_OBSERVATION
    ]
  });

  expect(result).toMatchObject({
    kind: "selected",
    reason: "KOREANET_LOWEST",
    lowestUnitPriceWon: 1000
  });
  expect(
    result.comparableCandidates.map((candidate) => candidate.product_id)
  ).toEqual(["12345678", "87654321"]);
});

test.each([
  [
    "high-first",
    [
      {
        ...KOREANET_OBSERVATION,
        observation_id: "koreanet-high",
        unit_price_won: 1100
      },
      {
        ...KOREANET_OBSERVATION,
        observation_id: "koreanet-low",
        product_id: "12345679",
        unit_price_won: 900
      },
      { ...COMPETITOR_OBSERVATION, unit_price_won: 1000 }
    ]
  ],
  [
    "low-first",
    [
      {
        ...KOREANET_OBSERVATION,
        observation_id: "koreanet-low",
        product_id: "12345679",
        unit_price_won: 900
      },
      {
        ...KOREANET_OBSERVATION,
        observation_id: "koreanet-high",
        unit_price_won: 1100
      },
      { ...COMPETITOR_OBSERVATION, unit_price_won: 1000 }
    ]
  ]
])(
  "Given K1100 K900 and C1000 in %s order When ranked Then K900 is selected independently of input order",
  (_caseName, candidates) => {
    const result = selectKoreaNetCandidate({
      ...SELECTION_TARGET,
      candidates
    });

    expect(result).toMatchObject({
      kind: "selected",
      reason: "KOREANET_LOWEST",
      selected: {
        observation_id: "koreanet-low",
        unit_price_won: 900
      },
      lowestUnitPriceWon: 900
    });
  }
);

test("Given repeated equal-price KoreaNet rows When ranked Then observation identity deterministically wins", () => {
  // Given
  const secondKoreaNet = {
    ...KOREANET_OBSERVATION,
    observation_id: "koreanet-z",
    product_id: "12345679"
  };

  // When
  const selections = [
    [KOREANET_OBSERVATION, secondKoreaNet],
    [secondKoreaNet, KOREANET_OBSERVATION]
  ].map(
    (koreaNetCandidates) =>
      selectKoreaNetCandidate({
        ...SELECTION_TARGET,
        candidates: [
          ...koreaNetCandidates,
          { ...COMPETITOR_OBSERVATION, unit_price_won: 1000 }
        ]
      }).selected?.observation_id
  );

  // Then
  expect(new Set(selections)).toEqual(new Set(["koreanet-a"]));
});
