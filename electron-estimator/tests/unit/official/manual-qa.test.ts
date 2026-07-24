import { expect, test } from "vitest";
import { loadOfficialRepository } from "../../../src/official/repository.js";
import { selectKoreaNetCandidate } from "../../../src/official/selector.js";
import {
  COMPETITOR_OBSERVATION,
  KOREANET_OBSERVATION,
  SELECTION_TARGET
} from "./fixtures.js";

test("Given the bundled catalog and KoreaNet matrix When the CLI scenario runs Then searches and provenance are observable", async () => {
  // Given
  const repository = await loadOfficialRepository();
  const matrix = [1100, 1000, 999].map((unitPriceWon) =>
    selectKoreaNetCandidate({
      ...SELECTION_TARGET,
      candidates: [
        KOREANET_OBSERVATION,
        { ...COMPETITOR_OBSERVATION, unit_price_won: unitPriceWon }
      ]
    })
  );

  // When
  const observable = {
    counts: [
      repository.marketPrices.length,
      repository.productivity.length,
      repository.wages.length
    ],
    searches: {
      CCTV: repository.marketPrices.filter((row) => row.category === "CCTV").length,
      LAN: repository.marketPrices.filter((row) => row.category === "LAN").length,
      FIBER: repository.marketPrices.filter((row) => row.category === "광케이블")
        .length
    },
    matrix: matrix.map((result) => ({
      reason: result.reason,
      autoSelected: result.autoSelected,
      provenance: result.selected?.source_payload_sha256 ?? null
    })),
    productionObservations: repository.sourcedProducts.length
  };
  process.stdout.write(`TASK8_MANUAL_QA=${JSON.stringify(observable)}\n`);

  // Then
  expect(observable).toEqual({
    counts: [64, 23, 10],
    searches: { CCTV: 22, LAN: 36, FIBER: 6 },
    matrix: [
      {
        reason: "KOREANET_LOWEST",
        autoSelected: true,
        provenance: KOREANET_OBSERVATION.source_payload_sha256
      },
      {
        reason: "KOREANET_TIED_LOWEST",
        autoSelected: true,
        provenance: KOREANET_OBSERVATION.source_payload_sha256
      },
      {
        reason: "LOWER_AUTHENTIC_CANDIDATE",
        autoSelected: false,
        provenance: null
      }
    ],
    productionObservations: 0
  });
});
