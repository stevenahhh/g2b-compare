import { DESIGN_CONTRACT } from "../../renderer/design-contract.js";
import { element } from "../../renderer/dom.js";
import type { NativeDraftRow, NativeWorkflowState } from "./state.js";
import { validateNativeWorkflow } from "./validation.js";

export async function loadCatalog(
  state: NativeWorkflowState,
  rerender: () => void
): Promise<void> {
  const response = await window.estimator.readSeed({ kind: "native_catalog" });
  if (response.ok && "marketPrices" in response.value) {
    state.catalog = response.value;
    state.status = "공식 카탈로그 준비됨.";
  } else if (response.ok) {
    state.status = "IPC_RESPONSE_REJECTED: 응답 형식이 올바르지 않음.";
  } else {
    state.status = `${response.error.code}: ${response.error.message}`;
  }
  rerender();
}

export async function runSelector(
  state: NativeWorkflowState,
  row: NativeDraftRow
): Promise<void> {
  const response = await window.estimator.readSeed({
    kind: "native_select",
    requestedItemKey: row.comparisonGroup,
    specification: row.specification,
    unit: row.unit
  });
  if (!response.ok) {
    row.selection = null;
    row.observation = null;
    state.status = `${response.error.code}: ${response.error.message}`;
    return;
  }
  if (!("kind" in response.value)) {
    row.selection = null;
    row.observation = null;
    state.status = "IPC_RESPONSE_REJECTED: 응답 형식이 올바르지 않음.";
    return;
  }
  const result = response.value;
  if (result.kind === "selected") {
    row.sourceKind = "sourced_observation";
    row.selection = result;
    row.observation = result.selected;
  } else if (result.reason === "LOWER_AUTHENTIC_CANDIDATE") {
    const observation = result.comparableCandidates[0] ?? null;
    row.selection = observation === null ? null : result;
    row.observation = observation;
  } else {
    row.selection = null;
    row.observation = null;
  }
  state.status = `Task8 판정 완료: ${result.reason}`;
}

export function openExportConfirmation(
  state: NativeWorkflowState,
  root: HTMLElement | null,
  updateDerived: () => void
): void {
  if (root === null || !validateNativeWorkflow(state).ok) {
    return;
  }
  const trigger = root.querySelector<HTMLButtonElement>(
    '[data-testid="export-workbook"]'
  );
  const acknowledgement = element("input", {
    attributes: {
      type: "checkbox",
      "data-testid": "export-warning-ack"
    }
  });
  const dialog = element("dialog", {
    className: "export-confirmation",
    attributes: { "data-testid": "export-confirmation" },
    children: [
      element("h2", { text: "내부검토 XLSX 저장 확인" }),
      element("p", { text: DESIGN_CONTRACT.disclaimers.always }),
      element("p", { text: DESIGN_CONTRACT.disclaimers.unsigned }),
      element("label", {
        className: "export-ack",
        children: [
          acknowledgement,
          element("span", { text: "고지 내용을 확인했음." })
        ]
      })
    ]
  });
  const cancel = dialogButton("취소", "cancel-export");
  const confirm = dialogButton("저장 계속", "confirm-export");
  confirm.disabled = true;
  acknowledgement.addEventListener("change", () => {
    confirm.disabled = !acknowledgement.checked;
  });
  const restore = (): void => {
    dialog.close();
    dialog.remove();
    trigger?.focus();
  };
  cancel.addEventListener("click", restore);
  confirm.addEventListener("click", () => {
    dialog.close();
    void performExport(state, dialog, trigger, updateDerived);
  });
  dialog.append(
    element("div", {
      className: "dialog-actions",
      children: [cancel, confirm]
    })
  );
  root.append(dialog);
  dialog.showModal();
  acknowledgement.focus();
}

async function performExport(
  state: NativeWorkflowState,
  dialog: HTMLDialogElement,
  trigger: HTMLButtonElement | null,
  updateDerived: () => void
): Promise<void> {
  const validation = validateNativeWorkflow(state);
  if (!validation.ok) {
    dialog.remove();
    trigger?.focus();
    updateDerived();
    return;
  }
  state.exporting = true;
  updateDerived();
  const selection = await window.estimator.dialog({ kind: "export" });
  if (!selection.ok || selection.value.cancelled) {
    state.status = selection.ok
      ? "저장이 취소됨."
      : `${selection.error.code}: ${selection.error.message}`;
  } else {
    const response = await window.estimator.export({
      kind: "native_workbook",
      capabilityId: selection.value.capabilityId,
      project: validation.wire
    });
    state.status = response.ok && "sheetCount" in response.value
      ? `저장 완료: ${response.value.workbookName} · ${String(response.value.sheetCount)}시트`
      : response.ok
        ? "IPC_RESPONSE_REJECTED: 응답 형식이 올바르지 않음."
        : `${response.error.code}: ${response.error.message}`;
  }
  state.exporting = false;
  dialog.remove();
  trigger?.focus();
  updateDerived();
  const result = trigger
    ?.closest<HTMLElement>('[data-testid="native-workflow"]')
    ?.querySelector<HTMLElement>('[data-testid="export-result"]');
  if (result !== null && result !== undefined) {
    result.textContent = state.status;
  }
}

function dialogButton(text: string, testId: string): HTMLButtonElement {
  return element("button", {
    className: "button button-secondary",
    text,
    attributes: { type: "button", "data-testid": testId }
  });
}
