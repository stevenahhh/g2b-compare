import { LegacyImportSessionSchema } from "../workflows/legacy/contracts.js";
import { openLegacyExportConfirmation } from "./legacy-workflow-export.js";
import {
  cellIndex,
  updateCellValue,
  validationErrors,
  type LegacyWorkflowState
} from "./legacy-workflow-state.js";
import {
  createLegacyWorkflowView,
  type LegacyWorkflowViewEvents,
  type LegacyWorkflowViewState
} from "./legacy-workflow-view.js";

export function renderLegacyWorkflow(container: HTMLElement): () => void {
  const lifecycle = new AbortController();
  const state: LegacyWorkflowState = {
    session: null,
    itemCount: 0,
    cells: [],
    errors: [],
    status: "",
    importing: false,
    exporting: false
  };
  let root: HTMLElement | null = null;
  let composingIndex: number | null = null;
  let pendingDelta = 0;

  const render = (focusTestId?: string): void => {
    if (lifecycle.signal.aborted) {
      return;
    }
    root = createLegacyWorkflowView({
      state: state satisfies LegacyWorkflowViewState,
      events
    });
    container.replaceChildren(root);
    if (focusTestId !== undefined) {
      root
        .querySelector<HTMLElement>(`[data-testid="${focusTestId}"]`)
        ?.focus();
    }
  };
  const updateValidation = (): void => {
    state.errors = validationErrors(state);
    const validation = root?.querySelector<HTMLElement>(
      '[data-testid="legacy-validation"]'
    );
    if (validation !== null && validation !== undefined) {
      validation.textContent =
        state.errors.length === 0 ? "내보내기 가능" : state.errors.join(" · ");
    }
    const button = root?.querySelector<HTMLButtonElement>(
      '[data-testid="export-legacy"]'
    );
    if (button !== null && button !== undefined) {
      button.disabled =
        state.session === null || state.errors.length > 0 || state.exporting;
    }
  };
  const focusCell = (input: HTMLInputElement, delta: number): void => {
    const index = cellIndex(input) + delta;
    root
      ?.querySelector<HTMLInputElement>(
        `[data-cell-index="${String(index)}"]`
      )
      ?.focus();
  };
  const events: LegacyWorkflowViewEvents = {
    importWorkbook: () => {
      void importWorkbook();
    },
    exportWorkbook: () => {
      if (root !== null) {
        openLegacyExportConfirmation({ root, state, render });
      }
    },
    openNative: () => {
      globalThis.dispatchEvent(new Event("estimator:open-native"));
    },
    updateItemCount: (input) => {
      state.itemCount = Number(input.value);
      updateValidation();
    },
    updateCell: (input) => {
      updateCellValue(state, input);
      if (composingIndex === null) {
        updateValidation();
      }
    },
    navigateCell: (input, event) => {
      const delta = navigationDelta(event.key);
      if (delta === 0) {
        return;
      }
      event.preventDefault();
      if (composingIndex !== null) {
        pendingDelta = delta;
        return;
      }
      focusCell(input, delta);
    },
    compositionStart: (input) => {
      composingIndex = cellIndex(input);
      pendingDelta = 0;
    },
    compositionEnd: (input) => {
      updateCellValue(state, input);
      const delta = pendingDelta;
      composingIndex = null;
      pendingDelta = 0;
      updateValidation();
      if (delta !== 0) {
        focusCell(input, delta);
      }
    }
  };

  async function importWorkbook(): Promise<void> {
    if (state.importing || state.exporting || lifecycle.signal.aborted) {
      return;
    }
    state.importing = true;
    render();
    const selection = await window.estimator.dialog({ kind: "import" });
    if (lifecycle.signal.aborted) {
      return;
    }
    if (!selection.ok || selection.value.cancelled) {
      state.importing = false;
      state.status = selection.ok ? "가져오기 취소됨." : selection.error.message;
      render("import-legacy");
      return;
    }
    const imported = await window.estimator.import({
      capabilityId: selection.value.capabilityId
    });
    if (lifecycle.signal.aborted) {
      return;
    }
    state.importing = false;
    if (!imported.ok) {
      state.status = imported.error.message;
      render("import-legacy");
      return;
    }
    const parsed = LegacyImportSessionSchema.safeParse(imported.value);
    if (!parsed.success) {
      state.status = "검증되지 않은 레거시 응답을 거부함.";
      render("import-legacy");
      return;
    }
    state.session = parsed.data;
    state.itemCount = parsed.data.itemCount;
    state.cells = parsed.data.editableCells.map((cell) => ({
      sheet: cell.sheet,
      address: cell.address,
      value: cell.value
    }));
    state.errors = validationErrors(state);
    state.status = `${parsed.data.profileId} 프로필 검증 완료.`;
    render("import-legacy");
  }

  render();
  return () => {
    root?.setAttribute("data-cleaned-up", "true");
    lifecycle.abort();
  };
}

function navigationDelta(key: string): number {
  if (key === "ArrowDown" || key === "ArrowRight" || key === "Enter") {
    return 1;
  }
  return key === "ArrowUp" || key === "ArrowLeft" ? -1 : 0;
}
