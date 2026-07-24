import type { SourcedProductObservation } from "../../src/official/schemas.js";
import { expect, test } from "vitest";
import {
  createNativeWorkbook,
  NativeWorkbookError
} from "../../src/native/workbook.js";
import { mixedNativeInput } from "./native-workbook-fixtures.js";

test("Given a synthetic KoreaNet observation When native input is parsed Then production workbook generation rejects it", async () => {
  // Given
  const input = await mixedNativeInput();
  const selection = input.koreaNetSelections[0];
  if (selection?.result.kind !== "selected") {
    expect.fail("Selected KoreaNet fixture is missing");
  }
  const syntheticSelected = {
    ...selection.result.selected,
    synthetic: true
  };
  const invalid = {
    ...input,
    koreaNetSelections: [
      {
        ...selection,
        result: {
          ...selection.result,
          selected: syntheticSelected,
          comparableCandidates: selection.result.comparableCandidates.map(
            (candidate) =>
              candidate.observation_id === syntheticSelected.observation_id
                ? syntheticSelected
                : candidate
          )
        }
      }
    ]
  };

  // When
  const result = createNativeWorkbook(invalid);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "KOREANET_SELECTION_CONFLICT"
  } satisfies Partial<NativeWorkbookError>);
});

test("Given a claimed tied KoreaNet minimum with a cheaper authentic candidate When native input is parsed Then selector recomputation rejects it", async () => {
  // Given
  const input = await mixedNativeInput();
  const selection = input.koreaNetSelections[0];
  if (selection?.result.kind !== "selected") {
    expect.fail("Selected KoreaNet fixture is missing");
  }
  const candidates = selection.result.comparableCandidates.map(withoutSynthetic);
  const selected = candidates.find(
    (candidate) =>
      candidate.observation_id === selection.result.selected.observation_id
  );
  if (selected === undefined) {
    expect.fail("Selected candidate is missing");
  }
  const selectionEvidence = selected.selection_evidence;
  if (selectionEvidence === undefined) {
    expect.fail("Selection evidence is missing");
  }
  const competitor = candidates.find(
    (candidate) => candidate.observation_id !== selected.observation_id
  );
  if (competitor === undefined) {
    expect.fail("Competitor candidate is missing");
  }
  const cheaper: SourcedProductObservation = {
    ...competitor,
    observation_id: "cheaper-native",
    product_id: "11223344",
    supplier_name: "Authentic Cheaper",
    unit_price_won: 900,
    source_url: "https://example.test/products/11223344",
    source_payload_sha256: "d".repeat(64),
    authenticity: {
      kind: "captured_source_payload",
      source_payload_sha256: "d".repeat(64)
    },
    selection_evidence: {
      ...selectionEvidence,
      auto_selected: false,
      lowest_observed_unit_price_won: 900,
      compared_observation_ids: [
        ...selectionEvidence.compared_observation_ids,
        "cheaper-native"
      ]
    }
  };
  const forged = {
    ...input,
    koreaNetSelections: [
      {
        ...selection,
        result: {
          ...selection.result,
          selected,
          comparableCandidates: [...candidates, cheaper]
        }
      }
    ]
  };

  // When
  const result = createNativeWorkbook(forged);

  // Then
  await expect(result).rejects.toMatchObject({
    code: "KOREANET_SELECTION_CONFLICT"
  } satisfies Partial<NativeWorkbookError>);
});

function withoutSynthetic(
  candidate: SourcedProductObservation
): SourcedProductObservation {
  const { synthetic, ...authentic } = candidate;
  void synthetic;
  return authentic;
}
