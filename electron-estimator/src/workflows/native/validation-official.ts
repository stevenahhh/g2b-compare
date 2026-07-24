import type { WageRow } from "../../official/schemas.js";
import type { NativeDraftRow, NativeWorkflowState, RateContextDraft } from "./state.js";
import type { NativeErrorCode } from "./validation.js";

export function marketCost(
  state: NativeWorkflowState,
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  const market = row.market;
  const context = rateContext(state.rateContext, state, codes);
  if (market === null) {
    codes.add("SOURCE_REQUIRED");
    return null;
  }
  return {
    kind: "market_price",
    provenance: {
      kind: "market_price",
      ...officialReference(state, market),
      sourcePdfPages: [market.source_pdf_page],
      workCode: market.work_code,
      specification: market.specification,
      unit: market.unit,
      materialIncluded: market.material_included,
      unitPriceWon: String(market.unit_price_krw)
    },
    rateContext: context
  };
}

export function productivityCost(
  state: NativeWorkflowState,
  row: NativeDraftRow,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  const productivity = row.productivity;
  const context = rateContext(state.rateContext, state, codes);
  if (productivity === null || state.catalog === null) {
    codes.add("SOURCE_REQUIRED");
    return null;
  }
  const wages = new Map(
    state.catalog.wages.map((wage) => [wage.job_code, wage])
  );
  const coefficients = Object.entries(
    productivity.coefficients_by_job_code
  ).flatMap(([jobCode, coefficient]) => {
    const wage = wages.get(jobCode);
    if (wage === undefined) {
      codes.add("SOURCE_REQUIRED");
      return [];
    }
    return [coefficientWire(state, jobCode, coefficient, wage)];
  });
  return {
    kind: "standard_quantity",
    provenance: {
      kind: "standard_quantity",
      ...officialReference(state, productivity),
      sourcePdfPages: productivity.source_pdf_pages,
      standardItem: productivity.standard_item,
      task: productivity.task,
      specification: productivity.specification,
      unit: productivity.unit,
      coefficients
    },
    rateContext: context
  };
}

function coefficientWire(
  state: NativeWorkflowState,
  jobCode: string,
  coefficient: string,
  wage: WageRow
): Readonly<Record<string, unknown>> {
  return {
    jobCode,
    coefficient,
    dailyWageWon: String(wage.daily_wage_krw),
    wageSource: {
      ...officialReference(state, wage),
      sourcePdfPages: wage.source_pdf_pages
    }
  };
}

function officialReference(
  state: NativeWorkflowState,
  source: {
    readonly source_id: string;
    readonly source_url: string;
    readonly source_pdf_sha256: string;
    readonly effective_from: string;
    readonly jurisdiction: string;
  }
): Readonly<Record<string, unknown>> {
  return {
    datasetVersion: state.catalog?.revision.datasetVersion,
    compositeSha256: state.catalog?.revision.compositeSha256,
    sourceManifestSha256: state.catalog?.revision.sourceManifestSha256,
    sourceId: source.source_id,
    sourceUrl: source.source_url,
    sourcePdfSha256: source.source_pdf_sha256,
    effectiveFrom: source.effective_from,
    jurisdiction: source.jurisdiction
  };
}

function rateContext(
  context: RateContextDraft,
  state: NativeWorkflowState,
  codes: Set<NativeErrorCode>
): Readonly<Record<string, unknown>> | null {
  if (
    context.issuer.trim().length === 0 ||
    context.regime === "" ||
    context.noticeOrContractDate === "" ||
    context.projectType.trim().length === 0 ||
    context.contractLevel === "" ||
    context.amountBasis.trim().length === 0 ||
    context.suppliedMaterials === "" ||
    context.pricingMethod.trim().length === 0 ||
    context.vatStatus === ""
  ) {
    codes.add("RATE_CONTEXT_REQUIRED");
    return null;
  }
  return {
    issuer: context.issuer,
    regime: context.regime,
    noticeOrContractDate: context.noticeOrContractDate,
    projectType: context.projectType,
    contractLevel: context.contractLevel,
    amountBasis: context.amountBasis,
    suppliedMaterials: context.suppliedMaterials,
    pricingMethod: context.pricingMethod,
    vatStatus: context.vatStatus,
    ...state.catalog?.revision
  };
}
