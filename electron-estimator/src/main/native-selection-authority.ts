import { isDeepStrictEqual } from "node:util";
import type { NativeWorkbookInput } from "../native/input.js";
import type { OfficialRepository } from "../official/repository.js";
import type { SourcedProductObservation } from "../official/schemas.js";
import { selectKoreaNetCandidate } from "../official/selector.js";

export class NativeSelectionAuthorityError extends Error {
  readonly name = "NativeSelectionAuthorityError";
}

export function assertMainOwnedSelections(
  project: NativeWorkbookInput,
  repository: OfficialRepository
): void {
  const selections = new Map(
    project.koreaNetSelections.map((selection) => [
      selection.lineId,
      selection.result
    ])
  );
  for (const entry of project.lines) {
    const provenance = entry.line.cost.kind === "direct"
      ? entry.line.cost.provenance
      : null;
    if (
      provenance?.kind === "direct" &&
      !selections.has(entry.line.id)
    ) {
      throw new NativeSelectionAuthorityError();
    }
  }
  for (const selection of project.koreaNetSelections) {
    if (
      selection.result.kind === "not_selected" &&
      selection.result.reason !== "LOWER_AUTHENTIC_CANDIDATE"
    ) {
      throw new NativeSelectionAuthorityError();
    }
    const line = project.lines.find(
      (entry) => entry.line.id === selection.lineId
    )?.line;
    const observation = selection.result.kind === "selected"
      ? selection.result.selected
      : selection.result.comparableCandidates[0];
    const group = observation?.selection_evidence?.comparison_group;
    if (line === undefined || group === undefined) {
      throw new NativeSelectionAuthorityError();
    }
    const trusted = selectKoreaNetCandidate({
      requestedItemKey: group,
      specification: line.specification,
      unit: line.unit,
      candidates: repository.sourcedProducts
    });
    if (!isDeepStrictEqual(trusted, selection.result)) {
      throw new NativeSelectionAuthorityError();
    }
    const trustedObservation = trusted.kind === "selected"
      ? trusted.selected
      : trusted.comparableCandidates[0];
    if (
      trustedObservation === undefined ||
      !matchesLineObservation(line, trustedObservation)
    ) {
      throw new NativeSelectionAuthorityError();
    }
  }
}

function matchesLineObservation(
  line: NativeWorkbookInput["lines"][number]["line"],
  observation: SourcedProductObservation
): boolean {
  if (
    line.cost.kind !== "direct" ||
    line.cost.provenance.kind !== "direct"
  ) {
    return false;
  }
  const source = line.cost.provenance;
  return (
    source.observationId === observation.observation_id &&
    source.productId === observation.product_id &&
    source.supplierName === observation.supplier_name &&
    source.unitPriceWon.equals(observation.unit_price_won) &&
    source.specification === observation.spec_snapshot &&
    source.unit === observation.unit &&
    source.sourceUrl === observation.source_url &&
    source.apiOperation === observation.api_operation &&
    source.observedAt === observation.observed_at &&
    source.sourcePayloadSha256 === observation.source_payload_sha256
  );
}
