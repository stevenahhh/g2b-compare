import { describe, expect, it } from "vitest";
import { parseNativeWorkbookInput } from "../../src/native/input.js";
import { loadOfficialRepository } from "../../src/official/repository.js";
import { selectKoreaNetCandidate } from "../../src/official/selector.js";
import {
  NativeSelectionAuthorityError,
  assertMainOwnedSelections
} from "../../src/main/native-selection-authority.js";
import {
  lowerAuthenticFixture,
  noComparableFixture
} from "../e2e/native-workflow.fixtures.js";
import { mixedNativeInput } from "../integration/native-workbook-fixtures.js";

describe("Given main-owned sourced-product authority", () => {
  it("rejects a self-consistent renderer selection absent from production", async () => {
    const input = parseNativeWorkbookInput(await mixedNativeInput());
    const production = await loadOfficialRepository();

    expect(() => assertMainOwnedSelections(input, production)).toThrow(
      NativeSelectionAuthorityError
    );
  });

  it("accepts the same selection only when the injected repository owns it", async () => {
    const input = parseNativeWorkbookInput(await mixedNativeInput());
    const production = await loadOfficialRepository();
    const selection = input.koreaNetSelections[0];
    if (selection === undefined) {
      expect.fail("Selection fixture is missing");
    }
    const trusted = {
      ...production,
      sourcedProducts: selection.result.comparableCandidates
    };

    expect(() => assertMainOwnedSelections(input, trusted)).not.toThrow();
  });

  it("allows user-entered quote lines without an automatic selection", async () => {
    const raw = await mixedNativeInput();
    const quoteOnly = parseNativeWorkbookInput({
      ...raw,
      lines: raw.lines.filter((entry) => entry.line.id !== "cctv-1"),
      koreaNetSelections: []
    });
    const production = await loadOfficialRepository();

    expect(() => assertMainOwnedSelections(quoteOnly, production)).not.toThrow();
  });

  it("rejects a trusted lower-candidate result bound to an unrelated direct source", async () => {
    const raw = await mixedNativeInput();
    const result = selectKoreaNetCandidate({
      requestedItemKey: lowerAuthenticFixture.comparisonGroup,
      specification: "CCTV 4MP",
      unit: "EA",
      candidates: lowerAuthenticFixture.candidates
    });
    const forged = parseNativeWorkbookInput({
      ...raw,
      lines: raw.lines.map((entry) =>
        entry.line.id === "cctv-1"
          ? {
              ...entry,
              line: {
                ...entry.line,
                specification: "CCTV 4MP",
                unit: "EA",
                cost: {
                  kind: "direct",
                  provenance: {
                    kind: "direct",
                    observationId: "unbound-observation",
                    productId: "11111111",
                    supplierName: "무관한 출처",
                    unitPriceWon: "900",
                    specification: "CCTV 4MP",
                    unit: "EA",
                    sourceUrl: "https://attacker.invalid/product/11111111",
                    apiOperation: "getProductInfo",
                    observedAt: "2026-07-23T10:00:00+09:00",
                    sourcePayloadSha256: "d".repeat(64)
                  }
                }
              }
            }
          : entry
      ),
      koreaNetSelections: [{ lineId: "cctv-1", result }]
    });
    const production = await loadOfficialRepository();
    const trusted = {
      ...production,
      sourcedProducts: lowerAuthenticFixture.candidates
    };

    expect(() => assertMainOwnedSelections(forged, trusted)).toThrow(
      NativeSelectionAuthorityError
    );
  });

  it("rejects a trusted no-comparable result even when bound to its only candidate", async () => {
    const raw = await mixedNativeInput();
    const result = selectKoreaNetCandidate({
      requestedItemKey: noComparableFixture.comparisonGroup,
      specification: "CCTV 4MP",
      unit: "EA",
      candidates: noComparableFixture.candidates
    });
    if (
      result.kind !== "not_selected" ||
      result.reason !== "NO_COMPARABLE_CANDIDATE"
    ) {
      expect.fail("No-comparable fixture must not auto-select");
    }
    const observation = result.comparableCandidates[0];
    if (observation === undefined) {
      expect.fail("No-comparable fixture is missing its candidate");
    }
    const bound = parseNativeWorkbookInput({
      ...raw,
      lines: raw.lines.map((entry) =>
        entry.line.id === "cctv-1"
          ? {
              ...entry,
              line: {
                ...entry.line,
                specification: observation.spec_snapshot,
                unit: observation.unit,
                cost: {
                  kind: "direct",
                  provenance: {
                    kind: "direct",
                    observationId: observation.observation_id,
                    productId: observation.product_id,
                    supplierName: observation.supplier_name,
                    unitPriceWon: String(observation.unit_price_won),
                    specification: observation.spec_snapshot,
                    unit: observation.unit,
                    sourceUrl: observation.source_url,
                    apiOperation: observation.api_operation,
                    observedAt: observation.observed_at,
                    sourcePayloadSha256: observation.source_payload_sha256
                  }
                }
              }
            }
          : entry
      ),
      koreaNetSelections: [{ lineId: "cctv-1", result }]
    });
    const production = await loadOfficialRepository();
    const trusted = {
      ...production,
      sourcedProducts: noComparableFixture.candidates
    };

    expect(() => assertMainOwnedSelections(bound, trusted)).toThrow(
      NativeSelectionAuthorityError
    );
  });
});
