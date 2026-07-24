import { element } from "./dom.js";
import type {
  LegacyWorkflowViewEvents,
  LegacyWorkflowViewState
} from "./legacy-workflow-view.js";
import type { LegacyImportSession } from "../workflows/legacy/contracts.js";

export function createLoadedWorkspace(
  state: LegacyWorkflowViewState,
  events: LegacyWorkflowViewEvents
): HTMLElement {
  const session = state.session;
  if (session === null) {
    throw new TypeError("LEGACY_SESSION_REQUIRED");
  }
  const count = element("input", {
    attributes: {
      type: "number",
      min: "0",
      max: String(session.capacity),
      "data-testid": "legacy-item-count"
    }
  });
  count.value = String(state.itemCount);
  count.addEventListener("input", () => events.updateItemCount(count));
  return element("div", {
    className: "legacy-workspace-scroll",
    children: [
      element("section", {
        className: "legacy-profile-summary",
        children: [
          definition("프로필", session.profileId),
          definition("용량", String(session.capacity), "profile-capacity"),
          definition("구조", session.layout, "profile-layout"),
          definition("기준 총액", won(session.totalWon), "preview-total", {
            "data-won": String(session.totalWon)
          }),
          element("label", {
            className: "field-label legacy-count",
            children: [element("span", { text: "활성 품목 수" }), count]
          })
        ]
      }),
      warningPanel(session),
      cellTable(state, events)
    ]
  });
}

export function createLegacyInspector(
  session: LegacyImportSession | null
): readonly Node[] {
  return session === null
    ? [element("p", { text: "가져온 원본 없음" })]
    : [
        element("h2", { text: "검증 경계" }),
        definition("원본 SHA-256", session.sourceSha256),
        definition("프로필", session.profileSlug),
        definition("수정 범위", "manifest MODEL_INPUT만"),
        definition("수식", "원본 보존 · Excel 재계산 필요")
      ];
}

export function createLegacyValidationFooter(
  state: LegacyWorkflowViewState
): HTMLElement {
  const message = state.errors.length === 0
    ? state.session === null ? "원본 선택 대기" : "내보내기 가능"
    : state.errors.join(" · ");
  return element("footer", {
    className: "native-validation-footer",
    children: [
      element("p", {
        text: message,
        attributes: {
          "data-testid": "legacy-validation",
          "aria-live": "polite"
        }
      }),
      element("p", {
        text: state.status,
        attributes: {
          "data-testid": "legacy-export-result",
          "aria-live": "polite"
        }
      })
    ]
  });
}

function warningPanel(session: LegacyImportSession): HTMLElement {
  const warnings = [
    `외부 링크 ${String(session.warnings.externalLinks)}개`,
    `캐시 오류 ${String(session.warnings.cachedFormulaErrors)}개`,
    `수식 참조 경고 ${String(session.warnings.formulaReferenceErrors)}개`,
    `문제 정의 이름 ${String(session.warnings.problemDefinedNames)}개`
  ];
  if (session.profileId === "C") {
    warnings.push("상속 오류 U13:U17: 원본 수식을 그대로 보존함.");
  }
  return element("section", {
    className: "legacy-warning-panel",
    children: [
      element("h2", { text: "원본 상속 경고" }),
      element("p", {
        text: warnings.join(" · "),
        attributes: { "data-testid": "inherited-warning" }
      }),
      element("p", {
        text:
          session.profileId === "C"
            ? "정식 교정값은 원본 작성자 확인이 필요하여 자동 교정하지 않음."
            : "경고 개수는 결과 검증 JSON에서 원본과 동일해야 함.",
        attributes: { "data-testid": "canonical-correction" }
      })
    ]
  });
}

function cellTable(
  state: LegacyWorkflowViewState,
  events: LegacyWorkflowViewEvents
): HTMLElement {
  const rows = state.cells.map((cell, index) => {
    const input = element("input", {
      attributes: {
        type: "text",
        "data-testid": "legacy-cell-input",
        "data-cell-index": String(index),
        "data-cell-key": `${cell.sheet}!${cell.address}`,
        "aria-label": `${cell.sheet} ${cell.address}`
      }
    });
    input.value = cell.value.kind === "blank" ? "" : cell.value.value;
    input.addEventListener("input", () => events.updateCell(input));
    input.addEventListener("keydown", (event) =>
      events.navigateCell(input, event)
    );
    input.addEventListener("compositionstart", () =>
      events.compositionStart(input)
    );
    input.addEventListener("compositionend", () =>
      events.compositionEnd(input)
    );
    return element("tr", {
      children: [
        element("td", { text: String(index + 1) }),
        element("td", { text: cell.sheet }),
        element("td", { text: cell.address }),
        element("td", { children: [input] })
      ]
    });
  });
  return element("section", {
    className: "legacy-table-region",
    children: [
      element("table", {
        className: "estimate-table legacy-table",
        children: [
          element("thead", {
            children: [
              element("tr", {
                children: ["#", "시트", "셀", "허용 값"].map((text) =>
                  element("th", { text })
                )
              })
            ]
          }),
          element("tbody", { children: rows })
        ]
      })
    ]
  });
}

function definition(
  term: string,
  description: string,
  testId?: string,
  attributes: Readonly<Record<string, string>> = {}
): HTMLElement {
  return element("dl", {
    className: "primitive-definition-list",
    children: [
      element("div", {
        className: "primitive-definition",
        children: [
          element("dt", { text: term }),
          element("dd", {
            text: description,
            attributes: {
              ...attributes,
              ...(testId === undefined ? {} : { "data-testid": testId })
            }
          })
        ]
      })
    ]
  });
}

function won(value: number): string {
  return `${new Intl.NumberFormat("ko-KR").format(value)}원`;
}
