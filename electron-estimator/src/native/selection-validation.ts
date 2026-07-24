import type { EstimateLine } from "../domain/estimate.js";
import type { KoreaNetSelectionResult } from "../official/selector.js";
import { selectKoreaNetCandidate } from "../official/selector.js";

export function isValidNativeKoreaNetSelection(
  line: EstimateLine | undefined,
  result: KoreaNetSelectionResult
): boolean {
  const requestedItemKey = comparisonGroup(result);
  if (
    line === undefined ||
    requestedItemKey === undefined ||
    hasSyntheticObservation(result)
  ) {
    return false;
  }
  const recomputed = selectKoreaNetCandidate({
    requestedItemKey,
    specification: line.specification,
    unit: line.unit,
    candidates: result.comparableCandidates
  });
  if (
    recomputed.kind !== result.kind ||
    recomputed.reason !== result.reason ||
    recomputed.lowestUnitPriceWon !== result.lowestUnitPriceWon
  ) {
    return false;
  }
  if (recomputed.kind === "not_selected" || result.kind === "not_selected") {
    return recomputed.selected === result.selected;
  }
  return JSON.stringify(recomputed.selected) === JSON.stringify(result.selected);
}

function comparisonGroup(
  result: KoreaNetSelectionResult
): string | undefined {
  if (result.kind === "selected") {
    return result.selected.selection_evidence?.comparison_group;
  }
  return result.comparableCandidates.find(
    (candidate) => candidate.selection_evidence !== undefined
  )?.selection_evidence?.comparison_group;
}

function hasSyntheticObservation(result: KoreaNetSelectionResult): boolean {
  return (
    (result.kind === "selected" && result.selected.synthetic === true) ||
    result.comparableCandidates.some((candidate) => candidate.synthetic === true)
  );
}
