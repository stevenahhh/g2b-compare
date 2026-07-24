import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import type { FrameIdentity } from "./capabilities.js";
import {
  exportLegacyWorkbook,
  LEGACY_EXPORT_DISCLAIMER_VERSION,
  type AtomicExportOptions
} from "../legacy/export/index.js";
import type { LegacyImportDto } from "../legacy/import.js";
import {
  LEGACY_PROFILE_FACTS,
  type LegacyExportRequest,
  type LegacyImportSession,
  type LegacyWorkflowErrorCode
} from "../workflows/legacy/contracts.js";
import {
  editableCells,
  hasMissingComparison,
  sameCellKeys
} from "./legacy-session-cells.js";

type StoredSession = {
  readonly frame: FrameIdentity;
  readonly sourcePath: string;
  readonly session: LegacyImportSession;
};

export type LegacyExportDependencies = {
  readonly appVersion: string;
  readonly manifestRoot: string;
  readonly exportOptions?: AtomicExportOptions;
};

export class LegacySessionError extends Error {
  readonly name = "LegacySessionError";

  constructor(readonly code: LegacyWorkflowErrorCode) {
    super(code);
  }
}

export class LegacySessionStore {
  readonly #sessions = new Map<string, StoredSession>();

  create(input: {
    readonly sourcePath: string;
    readonly sourceName: string;
    readonly imported: LegacyImportDto;
    readonly frame: FrameIdentity;
  }): LegacyImportSession {
    for (const [sessionId, stored] of this.#sessions) {
      if (
        stored.frame.processId === input.frame.processId &&
        stored.frame.routingId === input.frame.routingId
      ) {
        this.#sessions.delete(sessionId);
      }
    }
    const facts = LEGACY_PROFILE_FACTS[input.imported.profileId];
    const session = {
      schemaVersion: "legacy-ui-session-v1",
      sessionId: randomUUID(),
      sourceName: input.sourceName,
      profileId: input.imported.profileId,
      profileSlug: input.imported.profileSlug,
      sourceSha256: input.imported.sourceSha256,
      capacity: input.imported.capacity,
      itemCount: input.imported.items.length,
      totalWon: facts.totalWon,
      layout: facts.layout,
      editableCells: editableCells(input.imported),
      warnings: {
        externalLinks: input.imported.baselineInventory.externalLinks.count,
        cachedFormulaErrors:
          input.imported.baselineInventory.formulaErrors.cachedErrorCount,
        formulaReferenceErrors:
          input.imported.baselineInventory.formulaErrors.formulaTextCount,
        problemDefinedNames:
          input.imported.baselineInventory.definedNames.problemCount,
        inheritedFormulaCells:
          input.imported.inheritedWarnings.originalFormulaCells,
        disposition: input.imported.inheritedWarnings.disposition
      }
    } satisfies LegacyImportSession;
    this.#sessions.set(session.sessionId, {
      frame: input.frame,
      sourcePath: input.sourcePath,
      session
    });
    return session;
  }

  get(sessionId: string, frame: FrameIdentity): StoredSession {
    const stored = this.#sessions.get(sessionId);
    if (
      stored === undefined ||
      stored.frame.processId !== frame.processId ||
      stored.frame.routingId !== frame.routingId
    ) {
      throw new LegacySessionError("EXPORT_FAILED");
    }
    return stored;
  }
}

export async function exportLegacySession(input: {
  readonly request: LegacyExportRequest;
  readonly destination: string;
  readonly stored: StoredSession;
  readonly dependencies: LegacyExportDependencies;
}): Promise<
  | {
      readonly workbookName: string;
      readonly validationReportName: string;
    }
  | {
      readonly errorCode: LegacyWorkflowErrorCode;
      readonly message: string;
      readonly finalFilesPublished: 0;
    }
> {
  const failure = validateExport(input);
  if (failure !== undefined) {
    return workflowFailure(failure);
  }
  const facts = LEGACY_PROFILE_FACTS[input.stored.session.profileId];
  const manifestBytes = await readFile(
    path.join(input.dependencies.manifestRoot, facts.manifestName)
  );
  const result = await exportLegacyWorkbook(
    {
      sourcePath: input.stored.sourcePath,
      destinationPath: input.destination,
      expectedSourceSha256: input.stored.session.sourceSha256,
      itemCount: input.request.itemCount,
      cells: input.request.cells,
      manifestBytes,
      generatedAtUtc: new Date().toISOString(),
      build: {
        appVersion: input.dependencies.appVersion,
        commitSha256: "0".repeat(64),
        signed: false
      },
      officialSources: [],
      disclaimer: {
        checked: input.request.disclaimerChecked,
        version: LEGACY_EXPORT_DISCLAIMER_VERSION
      }
    },
    {
      ...input.dependencies.exportOptions,
      manifestRoot: pathToFileURL(
        `${input.dependencies.manifestRoot}${path.sep}`
      )
    }
  );
  if (!result.ok) {
    const code = result.error.code === "SOURCE_DESTINATION_CONFLICT"
      ? "SOURCE_OVERWRITE_FORBIDDEN"
      : "EXPORT_FAILED";
    return workflowFailure(code);
  }
  return {
    workbookName: result.workbookName,
    validationReportName: result.validationReportName
  };
}

function validateExport(input: {
  readonly request: LegacyExportRequest;
  readonly destination: string;
  readonly stored: StoredSession;
}): LegacyWorkflowErrorCode | undefined {
  const { request, stored } = input;
  if (!request.disclaimerChecked) {
    return "DISCLAIMER_REQUIRED";
  }
  if (
    path.resolve(input.destination).toLocaleLowerCase("en-US") ===
    path.resolve(stored.sourcePath).toLocaleLowerCase("en-US")
  ) {
    return "SOURCE_OVERWRITE_FORBIDDEN";
  }
  if (request.itemCount > stored.session.capacity) {
    return "PROFILE_CAPACITY_EXCEEDED";
  }
  if (
    stored.session.profileId === "A" &&
    (request.itemCount === 14 || request.itemCount === 15)
  ) {
    return "GROUP_BOUNDARY_BREACH";
  }
  const active = stored.session.editableCells.filter(
    (cell) => cell.position <= request.itemCount
  );
  if (!sameCellKeys(active, request.cells)) {
    return "EXPORT_FAILED";
  }
  return stored.session.profileId !== "A" &&
    hasMissingComparison(request.cells)
    ? "COMPARISON_REQUIRED"
    : undefined;
}

function workflowFailure(code: LegacyWorkflowErrorCode) {
  return {
    errorCode: code,
    message: code,
    finalFilesPublished: 0 as const
  };
}
