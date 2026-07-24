import { activeCells, type LegacyWorkflowState } from "./legacy-workflow-state.js";
import { DESIGN_CONTRACT } from "./design-contract.js";
import { element } from "./dom.js";

export function openLegacyExportConfirmation(input: {
  readonly root: HTMLElement;
  readonly state: LegacyWorkflowState;
  readonly render: (focusTestId?: string) => void;
}): void {
  const { root, state, render } = input;
  if (state.errors.length > 0 || state.session === null) {
    return;
  }
  const exportButton = root.querySelector<HTMLButtonElement>(
    '[data-testid="export-legacy"]'
  );
  const acknowledgement = element("input", {
    attributes: {
      type: "checkbox",
      "data-testid": "legacy-export-ack"
    }
  });
  const confirm = element("button", {
    className: "button button-primary",
    text: "저장 위치 선택",
    attributes: {
      type: "button",
      disabled: "",
      "data-testid": "confirm-legacy-export"
    }
  });
  const error = element("p", {
    text: "DISCLAIMER_REQUIRED: 내부 검토용이며 수식은 재계산되지 않음.",
    attributes: {
      "data-testid": "legacy-export-error",
      "aria-live": "polite"
    }
  });
  const cancel = element("button", {
    className: "button button-secondary",
    text: "취소",
    attributes: { type: "button" }
  });
  const modal = element("dialog", {
    className: "export-confirmation",
    attributes: {
      "data-testid": "legacy-export-confirmation",
      "aria-labelledby": "legacy-export-title"
    },
    children: [
      element("h2", {
        text: "검토초안 내보내기",
        attributes: { id: "legacy-export-title" }
      }),
      element("p", {
        text:
          "원본은 덮어쓰지 않으며 XLSX와 validation.json을 한 쌍으로 저장함."
      }),
      confirmationNotices(state.session),
      element("label", {
        className: "export-ack",
        children: [
          acknowledgement,
          element("span", {
            text: "내부 검토용·미재계산 결과임을 확인함."
          })
        ]
      }),
      error,
      element("div", {
        className: "dialog-actions",
        children: [cancel, confirm]
      })
    ]
  });
  const close = (): void => {
    modal.close();
    modal.remove();
    exportButton?.focus();
  };
  acknowledgement.addEventListener("change", () => {
    confirm.disabled = !acknowledgement.checked;
    error.textContent = acknowledgement.checked
      ? "확인됨. 저장 위치를 선택할 수 있음."
      : "DISCLAIMER_REQUIRED: 내부 검토용이며 수식은 재계산되지 않음.";
  });
  cancel.addEventListener("click", close);
  modal.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  confirm.addEventListener("click", () => {
    void performExport({ state, close, render });
  });
  root.append(modal);
  modal.showModal();
  acknowledgement.focus();
}

function confirmationNotices(
  session: NonNullable<LegacyWorkflowState["session"]>
): HTMLElement {
  const inherited = session.profileId === "C"
    ? "상속 오류 5개(U13:U17) · 자동 교정하지 않음"
    : `상속 오류 ${String(session.warnings.inheritedFormulaCells.length)}개`;
  return element("div", {
    className: "legacy-confirmation-notices",
    children: [
      element("p", {
        className: "notice legal-notice",
        text: DESIGN_CONTRACT.disclaimers.always,
        attributes: { "data-testid": "legacy-modal-legal" }
      }),
      element("p", {
        className: "notice unsigned-notice",
        text: DESIGN_CONTRACT.disclaimers.unsigned,
        attributes: { "data-testid": "legacy-modal-unsigned" }
      }),
      element("p", {
        text: `${inherited} · 외부 링크 ${String(session.warnings.externalLinks)}개`,
        attributes: { "data-testid": "legacy-modal-inherited" }
      }),
      element("p", {
        text: "공식자료 기준일: 미적용 · 고정 레거시 원본 기준",
        attributes: { "data-testid": "legacy-modal-official-date" }
      })
    ]
  });
}

async function performExport(input: {
  readonly state: LegacyWorkflowState;
  readonly close: () => void;
  readonly render: (focusTestId?: string) => void;
}): Promise<void> {
  const { state, close, render } = input;
  const session = state.session;
  if (session === null) {
    return;
  }
  state.exporting = true;
  const selection = await window.estimator.dialog({
    kind: "legacy_export"
  });
  if (!selection.ok || selection.value.cancelled) {
    state.exporting = false;
    state.status = selection.ok ? "저장 취소됨." : selection.error.message;
    close();
    render("export-legacy");
    return;
  }
  const response = await window.estimator.export({
    kind: "legacy_workbook",
    capabilityId: selection.value.capabilityId,
    sessionId: session.sessionId,
    itemCount: state.itemCount,
    cells: activeCells(state),
    disclaimerChecked: true
  });
  state.exporting = false;
  state.status = response.ok
    ? "errorCode" in response.value
      ? `${response.value.errorCode}: ${response.value.message}`
      : "validationReportName" in response.value
        ? `검증 파일 쌍 저장 완료: ${response.value.workbookName}`
        : "예상하지 않은 내보내기 응답"
    : response.error.message;
  close();
  render("export-legacy");
}
