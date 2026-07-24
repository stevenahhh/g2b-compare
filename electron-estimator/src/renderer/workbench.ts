import { element } from "./dom.js";
import { installWorkbenchInteractions } from "./workbench-interactions.js";
import {
  createWorkbenchState,
  type WorkbenchState
} from "./workbench-state.js";
import { createWorkbenchView } from "./workbench-view.js";
import type { WorkbenchRow } from "./workbench-model.js";

function filteredRows(state: WorkbenchState): WorkbenchRow[] {
  const query = state.query.trim().toLocaleLowerCase("ko-KR");
  return query.length === 0
    ? state.rows
    : state.rows.filter((row) =>
        `${row.itemName} ${row.specification} ${row.unit}`
          .toLocaleLowerCase("ko-KR")
          .includes(query)
      );
}

function selectedRow(
  state: WorkbenchState,
  visibleRows: readonly WorkbenchRow[]
): WorkbenchRow {
  if (!visibleRows.some((row) => row.id === state.selectedId)) {
    state.selectedId = visibleRows[0]?.id ?? state.rows[0]?.id ?? "";
  }
  const selected =
    state.rows.find((row) => row.id === state.selectedId) ?? state.rows[0];
  if (selected === undefined) {
    throw new TypeError("Workbench requires at least one row");
  }
  return selected;
}

export function renderWorkbench(container: HTMLElement): () => void {
  const state = createWorkbenchState();
  const root = element("main", {
    className: "workbench-shell",
    attributes: { "data-testid": "workbench-shell" }
  });
  const lifecycle = new AbortController();

  const updateStatus = (message = ""): void => {
    root.dataset["modelValue"] = state.rows[0]?.itemName ?? "";
    root.dataset["validationCount"] = String(state.validationCount);
    root.dataset["saveCount"] = String(state.saveCount);
    root.dataset["navigationCount"] = String(state.navigationCount);
    root.dataset["dirty"] = String(state.dirty);
    const dirty = root.querySelector<HTMLElement>('[data-testid="dirty-state"]');
    if (dirty !== null) {
      dirty.textContent = state.dirty ? "저장되지 않음" : "로컬 상태 저장됨";
      dirty.classList.toggle("is-dirty", state.dirty);
    }
    const live = root.querySelector<HTMLElement>('[data-testid="live-region"]');
    if (live !== null && message.length > 0) {
      live.textContent = message;
    }
  };

  const focusInspector = (): void => {
    const target =
      root.querySelector<HTMLButtonElement>('[data-testid="close-inspector"]') ??
      root.querySelector<HTMLElement>(
        '[data-testid="provenance-inspector"]'
      );
    if (target !== null) {
      target.dataset["initialFocus"] = "true";
      target.focus();
    }
  };

  const closeInspector = (): void => {
    state.inspectorOpen = false;
    render();
    root
      .querySelector<HTMLButtonElement>('[data-testid="open-inspector"]')
      ?.focus();
  };

  const render = (focusSearch = false): void => {
    const visibleRows = filteredRows(state);
    const selected = selectedRow(state, visibleRows);
    const narrow = globalThis.matchMedia("(max-width: 1024px)").matches;
    const densityChange = (event: Event): void => {
      if (!(event.currentTarget instanceof HTMLSelectElement)) {
        return;
      }
      const value = event.currentTarget.value;
      if (
        value === "compact" ||
        value === "regular" ||
        value === "comfortable"
      ) {
        state.density = value;
        render();
      }
    };
    root.replaceChildren(
      ...createWorkbenchView({
        state,
        visibleRows,
        selected,
        narrow,
        onOpenInspector: () => {
          state.inspectorOpen = true;
          render();
          focusInspector();
        },
        onCloseInspector: closeInspector,
        onSelectRow: (id) => {
          state.selectedId = id;
          render();
        },
        onDensityChange: densityChange,
        onNavigate: (section) => {
          state.activeNav = section;
          if (section === "provenance") {
            state.inspectorOpen = true;
          }
          render();
          if (section === "provenance") {
            focusInspector();
          } else {
            const selector =
              section === "estimate"
                ? '[data-testid="table-search"]'
                : '[data-testid="live-region"]';
            root.querySelector<HTMLElement>(selector)?.focus();
          }
        }
      })
    );
    if (narrow && state.inspectorOpen) {
      root
        .querySelector<HTMLElement>('[data-testid="left-rail"]')
        ?.setAttribute("inert", "");
      root
        .querySelector<HTMLElement>('[data-testid="center-pane"]')
        ?.setAttribute("inert", "");
    }
    updateStatus();
    if (focusSearch) {
      const search =
        root.querySelector<HTMLInputElement>('[data-testid="table-search"]');
      search?.focus();
      search?.setSelectionRange(search.value.length, search.value.length);
    }
  };

  installWorkbenchInteractions({
    root,
    state,
    lifecycle,
    render,
    updateStatus
  });
  root.addEventListener(
    "keydown",
    (event) => {
      const narrow = globalThis.matchMedia("(max-width: 1024px)").matches;
      if (event.key === "Tab" && state.inspectorOpen && narrow) {
        const inspector = root.querySelector<HTMLElement>(
          '[data-testid="provenance-inspector"]'
        );
        const focusable =
          inspector === null
            ? []
            : Array.from(
                inspector.querySelectorAll<HTMLElement>(
                  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
                )
              );
        const first = focusable[0];
        const last = focusable.at(-1);
        if (inspector !== null && first !== undefined && last !== undefined) {
          const active = document.activeElement;
          if (
            !inspector.contains(active) ||
            (event.shiftKey && active === first) ||
            (!event.shiftKey && active === last)
          ) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
          }
        }
        return;
      }
      if (
        event.key === "Escape" &&
        state.inspectorOpen &&
        narrow
      ) {
        event.preventDefault();
        closeInspector();
      }
    },
    { signal: lifecycle.signal }
  );
  const cleanup = (): void => {
    root.dataset["cleanedUp"] = "true";
    lifecycle.abort();
  };
  globalThis.addEventListener("beforeunload", cleanup, {
    once: true,
    signal: lifecycle.signal
  });
  container.replaceChildren(root);
  root.dataset["cleanedUp"] = "false";
  render();
  return cleanup;
}
