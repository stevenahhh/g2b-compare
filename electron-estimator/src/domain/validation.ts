import { z } from "zod";
import { EstimateInputSchema, type Estimate } from "./estimate.js";

const DomainErrorCodeSchema = z.enum([
  "NEGATIVE_QUANTITY",
  "PROFILE_CAPACITY_EXCEEDED",
  "PROVENANCE_CONFLICT",
  "STALE_PROVENANCE",
  "RATE_CONTEXT_REQUIRED",
  "INVALID_DECIMAL",
  "INVALID_ID",
  "INVALID_OPTION_PARENT",
  "INVALID_INPUT"
]);

export type DomainErrorCode = z.output<typeof DomainErrorCodeSchema>;

export class DomainValidationError extends Error {
  readonly name = "DomainValidationError";

  constructor(
    readonly code: DomainErrorCode,
    readonly path: readonly PropertyKey[]
  ) {
    super(code);
  }
}

type LineValidationContext = {
  readonly index: number;
  readonly refinement: z.RefinementCtx;
};

const ValidatedEstimateSchema = EstimateInputSchema.superRefine((estimate, context) => {
  if (estimate.lines.length > estimate.profile.capacity) {
    context.addIssue({
      code: "custom",
      message: "PROFILE_CAPACITY_EXCEEDED",
      path: ["lines"]
    });
  }
  const mainLineIds = new Set<string>();
  estimate.lines.forEach((line) => {
    switch (line.role.kind) {
      case "main":
        mainLineIds.add(line.id);
        break;
      case "bound_option":
      case "unbound_option":
        break;
      default:
        assertNever(line.role);
    }
  });
  estimate.lines.forEach((line, index) => {
    const location = { index, refinement: context };
    switch (line.role.kind) {
      case "main":
      case "unbound_option":
        break;
      case "bound_option":
        if (!mainLineIds.has(line.role.parentLineId)) {
          context.addIssue({
            code: "custom",
            message: "INVALID_OPTION_PARENT",
            path: ["lines", index, "role", "parentLineId"]
          });
        }
        break;
      default:
        assertNever(line.role);
    }
    switch (line.cost.kind) {
      case "direct":
        verifySpecification(line, line.cost.provenance, location);
        break;
      case "three_company_min":
        line.cost.quotes.forEach((quote) => {
          verifySpecification(line, quote.provenance, location);
        });
        break;
      case "market_price":
        verifySpecification(line, line.cost.provenance, location);
        verifyRevision(
          line.cost.provenance,
          line.cost.rateContext,
          location
        );
        break;
      case "standard_quantity": {
        const rateContext = line.cost.rateContext;
        verifySpecification(line, line.cost.provenance, location);
        verifyRevision(
          line.cost.provenance,
          rateContext,
          location
        );
        line.cost.provenance.coefficients.forEach((coefficient) => {
          verifyRevision(
            coefficient.wageSource,
            rateContext,
            location
          );
        });
        break;
      }
      default:
        assertNever(line.cost);
    }
  });
});

export function parseEstimateInput(input: unknown): Estimate {
  const result = ValidatedEstimateSchema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  const issue = result.error.issues[0];
  const path = issue?.path ?? [];
  const explicit = DomainErrorCodeSchema.safeParse(issue?.message);
  if (explicit.success) {
    throw new DomainValidationError(explicit.data, path);
  }
  if (path.includes("rateContext")) {
    throw new DomainValidationError("RATE_CONTEXT_REQUIRED", path);
  }
  if (path.includes("cost") || path.includes("provenance")) {
    throw new DomainValidationError("PROVENANCE_CONFLICT", path);
  }
  throw new DomainValidationError("INVALID_INPUT", path);
}

function verifySpecification(
  line: {
    readonly specification: string;
    readonly unit: string;
  },
  provenance: {
    readonly specification: string;
    readonly unit: string;
  },
  location: LineValidationContext
): void {
  if (
    provenance.specification !== line.specification ||
    provenance.unit !== line.unit
  ) {
    location.refinement.addIssue({
      code: "custom",
      message: "PROVENANCE_CONFLICT",
      path: ["lines", location.index, "cost", "provenance"]
    });
  }
}

function verifyRevision(
  provenance: {
    readonly datasetVersion: string;
    readonly compositeSha256: string;
    readonly sourceManifestSha256: string;
  },
  rateContext: {
    readonly datasetVersion: string;
    readonly compositeSha256: string;
    readonly sourceManifestSha256: string;
  },
  location: LineValidationContext
): void {
  if (
    provenance.datasetVersion !== rateContext.datasetVersion ||
    provenance.compositeSha256 !== rateContext.compositeSha256 ||
    provenance.sourceManifestSha256 !== rateContext.sourceManifestSha256
  ) {
    location.refinement.addIssue({
      code: "custom",
      message: "STALE_PROVENANCE",
      path: ["lines", location.index, "cost", "provenance"]
    });
  }
}

function assertNever(value: never): never {
  throw new TypeError(`Unexpected cost method: ${String(value)}`);
}
