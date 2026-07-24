import { z } from "zod";
import {
  type SourcedProductObservation,
  SourcedProductObservationSchema
} from "./schemas.js";

const SelectionRequestSchema = z
  .strictObject({
    requestedItemKey: z.string().trim().min(1),
    specification: z.string().trim().min(1),
    unit: z.string().trim().min(1),
    candidates: z.array(z.unknown()).readonly()
  })
  .readonly();

export type KoreaNetSelectionReason =
  | "KOREANET_LOWEST"
  | "KOREANET_NOT_AVAILABLE"
  | "KOREANET_TIED_LOWEST"
  | "LOWER_AUTHENTIC_CANDIDATE"
  | "NO_COMPARABLE_CANDIDATE"
  | "SOURCE_EVIDENCE_INCOMPLETE"
  | "SPECIFICATION_MISMATCH"
  | "UNIT_MISMATCH";

export type KoreaNetSelectionResult =
  | {
      readonly kind: "selected";
      readonly autoSelected: true;
      readonly reason: "KOREANET_LOWEST" | "KOREANET_TIED_LOWEST";
      readonly selected: SourcedProductObservation;
      readonly lowestUnitPriceWon: number;
      readonly comparableCandidates: readonly SourcedProductObservation[];
    }
  | {
      readonly kind: "not_selected";
      readonly autoSelected: false;
      readonly reason: Exclude<
        KoreaNetSelectionReason,
        "KOREANET_LOWEST" | "KOREANET_TIED_LOWEST"
      >;
      readonly selected: null;
      readonly lowestUnitPriceWon: number | null;
      readonly comparableCandidates: readonly SourcedProductObservation[];
    };

export function selectKoreaNetCandidate(
  input: unknown
): KoreaNetSelectionResult {
  const request = SelectionRequestSchema.parse(input);
  const koreaNetRawCandidates = request.candidates.filter(
    (candidate) =>
      isRawKoreaNet(candidate) &&
      isRawComparisonGroup(candidate, request.requestedItemKey)
  );
  if (koreaNetRawCandidates.length === 0) {
    return selectionFailure("KOREANET_NOT_AVAILABLE", [], null);
  }
  const koreaNetResults = koreaNetRawCandidates.map((candidate) =>
    SourcedProductObservationSchema.safeParse(candidate)
  );
  if (
    koreaNetResults.some(
      (result) =>
        !result.success ||
        !isAuthentic(result.data) ||
        !hasCompleteKoreaEvidence(result.data)
    )
  ) {
    return selectionFailure("SOURCE_EVIDENCE_INCOMPLETE", [], null);
  }
  const koreaNetCandidates = koreaNetResults.flatMap((result) =>
    result.success ? [result.data] : []
  );
  const matchingSpecification = koreaNetCandidates.filter(
    (candidate) => candidate.spec_snapshot === request.specification
  );
  if (matchingSpecification.length === 0) {
    return selectionFailure("SPECIFICATION_MISMATCH", [], null);
  }
  const matchingUnit = matchingSpecification
    .filter((candidate) => candidate.unit === request.unit)
    .sort(compareCandidates);
  if (matchingUnit.length === 0) {
    return selectionFailure("UNIT_MISMATCH", [], null);
  }
  const koreaNet = matchingUnit[0];
  if (koreaNet === undefined) {
    return selectionFailure("KOREANET_NOT_AVAILABLE", [], null);
  }

  const comparableCandidates = request.candidates
    .map((candidate) => SourcedProductObservationSchema.safeParse(candidate))
    .filter(
      (
        result
      ): result is {
        readonly success: true;
        readonly data: SourcedProductObservation;
      } =>
        result.success &&
        isAuthentic(result.data) &&
        result.data.selection_evidence?.comparison_group ===
          request.requestedItemKey &&
        result.data.spec_snapshot === request.specification &&
        result.data.unit === request.unit
    )
    .map((result) => result.data)
    .sort(compareCandidates);
  const frozenCandidates = Object.freeze(comparableCandidates);
  if (frozenCandidates.length < 2) {
    return selectionFailure(
      "NO_COMPARABLE_CANDIDATE",
      frozenCandidates,
      koreaNet.unit_price_won
    );
  }
  const lowestUnitPriceWon = frozenCandidates[0]?.unit_price_won;
  if (
    lowestUnitPriceWon === undefined ||
    koreaNet.unit_price_won > lowestUnitPriceWon
  ) {
    return selectionFailure(
      "LOWER_AUTHENTIC_CANDIDATE",
      frozenCandidates,
      lowestUnitPriceWon ?? null
    );
  }
  const tied =
    frozenCandidates.filter(
      (candidate) => candidate.unit_price_won === koreaNet.unit_price_won
    ).length > 1;
  return Object.freeze({
    kind: "selected",
    autoSelected: true,
    reason: tied ? "KOREANET_TIED_LOWEST" : "KOREANET_LOWEST",
    selected: koreaNet,
    lowestUnitPriceWon,
    comparableCandidates: frozenCandidates
  });
}

function isRawKoreaNet(value: unknown): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    "supplier_name" in value &&
    typeof value.supplier_name === "string" &&
    /코리아넷|koreanet/iu.test(value.supplier_name)
  );
}

function isRawComparisonGroup(value: unknown, requestedItemKey: string): boolean {
  return (
    value !== null &&
    typeof value === "object" &&
    "selection_evidence" in value &&
    value.selection_evidence !== null &&
    typeof value.selection_evidence === "object" &&
    "comparison_group" in value.selection_evidence &&
    value.selection_evidence.comparison_group === requestedItemKey
  );
}

function compareCandidates(
  left: SourcedProductObservation,
  right: SourcedProductObservation
): number {
  return (
    left.unit_price_won - right.unit_price_won ||
    left.observation_id.localeCompare(right.observation_id)
  );
}

function isAuthentic(candidate: SourcedProductObservation): boolean {
  return (
    candidate.authenticity?.kind === "captured_source_payload" &&
    candidate.authenticity.source_payload_sha256 ===
      candidate.source_payload_sha256
  );
}

function hasCompleteKoreaEvidence(
  candidate: SourcedProductObservation
): boolean {
  const evidence = [
    candidate.supplier_location_evidence,
    candidate.service_area_evidence
  ];
  return evidence.every(
    (item) =>
      item !== undefined &&
      item.source_url === candidate.source_url &&
      item.observed_at === candidate.observed_at &&
      item.source_payload_sha256 === candidate.source_payload_sha256
  );
}

function selectionFailure(
  reason: Exclude<
    KoreaNetSelectionReason,
    "KOREANET_LOWEST" | "KOREANET_TIED_LOWEST"
  >,
  comparableCandidates: readonly SourcedProductObservation[],
  lowestUnitPriceWon: number | null
): KoreaNetSelectionResult {
  return Object.freeze({
    kind: "not_selected",
    autoSelected: false,
    reason,
    selected: null,
    lowestUnitPriceWon,
    comparableCandidates
  });
}
