import type { PatchCellInput } from "../legacy/patch/types.js";
import type {
  LegacyImportSession,
  LegacyWorkflowErrorCode
} from "../workflows/legacy/contracts.js";

export type LegacyWorkflowState = {
  session: LegacyImportSession | null;
  itemCount: number;
  cells: PatchCellInput[];
  errors: LegacyWorkflowErrorCode[];
  status: string;
  importing: boolean;
  exporting: boolean;
};

export function validationErrors(
  state: LegacyWorkflowState
): LegacyWorkflowErrorCode[] {
  const session = state.session;
  if (session === null) {
    return [];
  }
  const errors: LegacyWorkflowErrorCode[] = [];
  if (
    !Number.isInteger(state.itemCount) ||
    state.itemCount < 0 ||
    state.itemCount > session.capacity
  ) {
    errors.push("PROFILE_CAPACITY_EXCEEDED");
  }
  if (
    session.profileId === "A" &&
    (state.itemCount === 14 || state.itemCount === 15)
  ) {
    errors.push("GROUP_BOUNDARY_BREACH");
  }
  if (
    session.profileId !== "A" &&
    missingComparison(session, state)
  ) {
    errors.push("COMPARISON_REQUIRED");
  }
  return errors;
}

export function activeCells(
  state: LegacyWorkflowState
): readonly PatchCellInput[] {
  const session = state.session;
  if (session === null) {
    return [];
  }
  const allowed = new Set(
    session.editableCells
      .filter((cell) => cell.position <= state.itemCount)
      .map((cell) => `${cell.sheet}!${cell.address}`)
  );
  return state.cells.filter((cell) =>
    allowed.has(`${cell.sheet}!${cell.address}`)
  );
}

export function updateCellValue(
  state: LegacyWorkflowState,
  input: HTMLInputElement
): void {
  const index = cellIndex(input);
  const current = state.cells[index];
  if (current === undefined) {
    return;
  }
  const value = input.value === ""
    ? { kind: "blank" } as const
    : current.value.kind === "number" &&
        /^(?:0|[1-9]\d*)(?:\.\d+)?$/u.test(input.value)
      ? { kind: "number", value: input.value } as const
      : { kind: "text", value: input.value } as const;
  state.cells[index] = { ...current, value };
}

export function cellIndex(input: HTMLInputElement): number {
  return Number(input.dataset["cellIndex"] ?? "-1");
}

function missingComparison(
  session: LegacyImportSession,
  state: LegacyWorkflowState
): boolean {
  const values = new Map(
    state.cells.map((cell) => [`${cell.sheet}!${cell.address}`, cell.value])
  );
  return session.editableCells
    .filter((cell) => cell.position <= state.itemCount)
    .filter((cell) =>
      cell.sheet === "단가조사" &&
      ["H", "L", "P"].includes(cell.address.replace(/\d+$/u, ""))
    )
    .some((cell) => {
      const value = values.get(`${cell.sheet}!${cell.address}`);
      return value?.kind !== "number" || Number(value.value) <= 0;
    });
}
