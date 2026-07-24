import { element } from "../../renderer/dom.js";
import {
  loadCatalog,
  openExportConfirmation,
  runSelector
} from "./controller-actions.js";
import {
  addDraftRow,
  createNativeWorkflowState,
  normalizeField,
  selectedDraftRow
} from "./state.js";
import { validateNativeWorkflow } from "./validation.js";
import { createNativeWorkflowView } from "./view.js";
import type { NativeViewEvents } from "./view-types.js";

const NUMBER = new Intl.NumberFormat("ko-KR");

export function renderNativeWorkflow(container: HTMLElement): () => void {
  const state = createNativeWorkflowState();
  const lifecycle = new AbortController();
  let workflowRoot: HTMLElement | null = null;

  const updateDerived = (): void => {
    if (workflowRoot === null) {
      return;
    }
    const validation = validateNativeWorkflow(state);
    const errors = workflowRoot.querySelector<HTMLElement>(
      '[data-testid="validation-errors"]'
    );
    if (errors !== null) {
      errors.replaceChildren(
        ...(validation.ok
          ? []
          : validation.messages.map((message) =>
              element("li", { text: message })
            ))
      );
    }
    const exportButton = workflowRoot.querySelector<HTMLButtonElement>(
      '[data-testid="export-workbook"]'
    );
    if (exportButton !== null) {
      exportButton.disabled = !validation.ok || state.exporting;
    }
    const total = workflowRoot.querySelector<HTMLElement>(
      '[data-testid="preview-total"]'
    );
    if (total !== null) {
      const won = validation.ok
        ? validation.calculation.roundedTotalWon.toFixed(0)
        : "0";
      total.dataset["won"] = won;
      total.textContent = `${NUMBER.format(Number(won))}원`;
    }
    state.rows.forEach((row) => {
      const amount = workflowRoot?.querySelector<HTMLElement>(
        `[data-line-amount="${row.id}"]`
      );
      const calculated = validation.ok
        ? validation.calculation.lines.find((line) => line.lineId === row.id)
        : undefined;
      if (amount !== null && amount !== undefined) {
        amount.textContent =
          calculated === undefined
            ? "검증 필요"
            : `${NUMBER.format(calculated.amountWon.toNumber())}원`;
      }
    });
  };

  const rerender = (focusCatalog = false): void => {
    if (lifecycle.signal.aborted) {
      return;
    }
    const next = createNativeWorkflowView({ state, events });
    container.replaceChildren(next);
    workflowRoot = next;
    updateDerived();
    if (
      globalThis.matchMedia("(max-width: 1024px)").matches &&
      state.inspectorOpen
    ) {
      next
        .querySelector<HTMLElement>('[data-testid="left-rail"]')
        ?.setAttribute("inert", "");
      next
        .querySelector<HTMLElement>('[data-testid="center-pane"]')
        ?.setAttribute("inert", "");
      next.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          events.closeInspector();
        }
      });
    }
    if (focusCatalog) {
      const search = next.querySelector<HTMLInputElement>(
        '[data-testid="catalog-search"]'
      );
      search?.focus();
      search?.setSelectionRange(search.value.length, search.value.length);
    }
  };

  const events: NativeViewEvents = {
    updateDerived,
    rerender,
    addRow: () => {
      addDraftRow(state);
      rerender();
    },
    selectRow: (row) => {
      state.selectedId = row.id;
      rerender();
    },
    addMarket: (market, mode) => {
      const row =
        mode === "new"
          ? addDraftRow(state, normalizeField(market.category))
          : selectedDraftRow(state) ?? addDraftRow(state);
      row.field = normalizeField(market.category);
      row.itemName = market.name;
      row.specification = market.specification;
      row.unit = market.unit;
      row.method = "market_price";
      row.market = market;
      rerender();
    },
    addProductivity: (productivity, mode) => {
      const row =
        mode === "new"
          ? addDraftRow(state, normalizeField(productivity.category))
          : selectedDraftRow(state) ?? addDraftRow(state);
      row.field = normalizeField(productivity.category);
      row.itemName = productivity.task;
      row.specification = productivity.specification;
      row.unit = productivity.unit;
      row.method = "standard_quantity";
      row.productivity = productivity;
      rerender();
    },
    runSelector: async (row) => {
      await runSelector(state, row);
      rerender();
    },
    openExport: () => openExportConfirmation(state, workflowRoot, updateDerived),
    openInspector: () => {
      state.inspectorOpen = true;
      rerender();
      workflowRoot
        ?.querySelector<HTMLButtonElement>('[data-testid="close-inspector"]')
        ?.focus();
    },
    closeInspector: () => {
      state.inspectorOpen = false;
      rerender();
      workflowRoot
        ?.querySelector<HTMLButtonElement>('[data-testid="open-inspector"]')
        ?.focus();
    }
  };

  rerender();
  void loadCatalog(state, rerender);
  const cleanup = (): void => {
    workflowRoot?.setAttribute("data-cleaned-up", "true");
    lifecycle.abort();
  };
  globalThis.addEventListener("beforeunload", cleanup, {
    once: true,
    signal: lifecycle.signal
  });
  return cleanup;
}
