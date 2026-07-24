import type { WorkbenchState } from "./workbench-state.js";
import { parseField, updateRow } from "./workbench-state.js";

type InteractionOptions = {
  readonly root: HTMLElement;
  readonly state: WorkbenchState;
  readonly lifecycle: AbortController;
  readonly render: (focusSearch?: boolean) => void;
  readonly updateStatus: (message?: string) => void;
};

const NAVIGATION_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Enter"
]);

function gridInput(target: EventTarget | null): HTMLInputElement | null {
  return target instanceof HTMLInputElement &&
    target.hasAttribute("data-grid-row") &&
    target.hasAttribute("data-grid-column")
    ? target
    : null;
}

function moveGridFocus(
  root: HTMLElement,
  input: HTMLInputElement,
  rowDelta: number,
  columnDelta: number
): void {
  const row = Number(input.getAttribute("data-grid-row"));
  const column = Number(input.getAttribute("data-grid-column"));
  root
    .querySelector<HTMLInputElement>(
      `[data-grid-row="${String(row + rowDelta)}"][data-grid-column="${String(column + columnDelta)}"]`
    )
    ?.focus();
}

function writeInput(state: WorkbenchState, input: HTMLInputElement): void {
  const field = parseField(input.getAttribute("data-field"));
  const rowId = input.closest<HTMLTableRowElement>("[data-row-id]")?.dataset[
    "rowId"
  ];
  const row = state.rows.find((candidate) => candidate.id === rowId);
  if (field !== null && row !== undefined) {
    updateRow(row, field, input.value);
  }
}

function validationError(input: HTMLInputElement): string | null {
  const field = parseField(input.getAttribute("data-field"));
  const value = input.value.trim();
  if (
    field === "itemName" ||
    field === "specification" ||
    field === "unit"
  ) {
    return value.length === 0 ? "필수 텍스트를 입력해야 함." : null;
  }
  if (field === "quantity") {
    const quantity = Number(value);
    return Number.isFinite(quantity) && quantity > 0
      ? null
      : "수량은 0보다 큰 숫자여야 함.";
  }
  if (field === "unitPriceWon") {
    const price = Number(value.replaceAll(",", ""));
    return Number.isSafeInteger(price) && price > 0
      ? null
      : "적용단가는 0보다 큰 정수여야 함.";
  }
  return "편집 필드를 확인할 수 없음.";
}

function onInput(options: InteractionOptions, event: Event): void {
  if (
    event.target instanceof HTMLInputElement &&
    event.target.matches('[data-testid="table-search"]')
  ) {
    options.state.query = event.target.value;
    options.render(true);
    return;
  }
  const input = gridInput(event.target);
  if (input !== null && options.state.composing !== input) {
    writeInput(options.state, input);
    options.state.dirty = true;
    options.updateStatus();
  }
}

function onCompositionStart(state: WorkbenchState, event: CompositionEvent): void {
  const input = gridInput(event.target);
  if (input !== null) {
    state.composing = input;
    state.pendingNavigation = false;
  }
}

function onCompositionEnd(
  options: InteractionOptions,
  event: CompositionEvent
): void {
  const input = gridInput(event.target);
  const { state } = options;
  if (input === null || state.composing !== input) {
    return;
  }
  state.composing = null;
  state.validationCount += 1;
  const error = validationError(input);
  if (error !== null) {
    input.setAttribute("aria-invalid", "true");
    state.pendingNavigation = false;
    state.dirty = true;
    options.updateStatus(`오류: ${error} 저장 차단됨.`);
    return;
  }
  input.removeAttribute("aria-invalid");
  writeInput(state, input);
  state.saveCount += 1;
  if (state.pendingNavigation) {
    state.navigationCount += 1;
    moveGridFocus(options.root, input, 0, 1);
  }
  state.pendingNavigation = false;
  state.dirty = false;
  options.updateStatus(`${input.value} 입력, 검증 및 저장 완료.`);
}

function handleEditingKey(
  options: InteractionOptions,
  input: HTMLInputElement,
  event: KeyboardEvent
): boolean {
  if (event.key === "F2") {
    event.preventDefault();
    options.state.editBaseline = input.value;
    input.dataset["editing"] = "true";
    input.select();
    return true;
  }
  if (event.key === "Escape" && input.dataset["editing"] === "true") {
    event.preventDefault();
    input.value = options.state.editBaseline;
    writeInput(options.state, input);
    input.dataset["editing"] = "false";
    options.state.dirty = false;
    options.updateStatus("편집 취소됨.");
    return true;
  }
  return false;
}

function onGridKeydown(
  options: InteractionOptions,
  input: HTMLInputElement,
  event: KeyboardEvent
): void {
  const { state } = options;
  if (state.composing === input && NAVIGATION_KEYS.has(event.key)) {
    event.preventDefault();
    state.pendingNavigation = true;
    return;
  }
  if (handleEditingKey(options, input, event)) {
    return;
  }
  const moves = {
    ArrowUp: [-1, 0],
    ArrowDown: [1, 0],
    ArrowLeft: [0, -1],
    ArrowRight: [0, 1],
    Enter: [1, 0]
  } as const;
  const move = Reflect.get(moves, event.key);
  if (!Array.isArray(move)) {
    return;
  }
  event.preventDefault();
  if (event.key === "Enter") {
    state.validationCount += 1;
    const error = validationError(input);
    if (error !== null) {
      input.setAttribute("aria-invalid", "true");
      state.dirty = true;
      options.updateStatus(`오류: ${error} 저장 차단됨.`);
      return;
    }
    input.removeAttribute("aria-invalid");
    writeInput(state, input);
    state.saveCount += 1;
    state.dirty = false;
  }
  state.navigationCount += 1;
  moveGridFocus(options.root, input, move[0], move[1]);
  options.updateStatus();
}

export function installWorkbenchInteractions(options: InteractionOptions): void {
  const listener = { signal: options.lifecycle.signal } as const;
  options.root.addEventListener("input", (event) => onInput(options, event), listener);
  options.root.addEventListener(
    "compositionstart",
    (event) => onCompositionStart(options.state, event),
    listener
  );
  options.root.addEventListener(
    "compositionend",
    (event) => onCompositionEnd(options, event),
    listener
  );
  options.root.addEventListener(
    "keydown",
    (event) => {
      const input = gridInput(event.target);
      if (input !== null) {
        onGridKeydown(options, input, event);
      }
    },
    listener
  );
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.ctrlKey && event.key.toLocaleLowerCase("en-US") === "f") {
        event.preventDefault();
        options.root
          .querySelector<HTMLInputElement>('[data-testid="table-search"]')
          ?.focus();
      }
    },
    listener
  );
}
