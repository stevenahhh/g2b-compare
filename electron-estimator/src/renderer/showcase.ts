import { DESIGN_CONTRACT } from "./design-contract.js";
import { element } from "./dom.js";

const densityRows = [
  ["compact", "26px", "압축 행"],
  ["regular", "32px", "기본 행"],
  ["comfortable", "40px", "여유 행"]
] as const;

function showcaseTable(): HTMLTableElement {
  const table = element("table", {
    className: "primitive-table",
    attributes: { "aria-label": "행 밀도 primitive" }
  });
  const headRow = element("tr");
  for (const label of ["상태", "높이", "예시"]) {
    headRow.append(element("th", { text: label, attributes: { scope: "col" } }));
  }
  table.append(element("thead", { children: [headRow] }));
  const body = element("tbody");
  for (const [density, height, label] of densityRows) {
    body.append(
      element("tr", {
        className: `row-${density}`,
        attributes: { "data-testid": `primitive-row-${density}` },
        children: [
          element("td", { text: density }),
          element("td", { text: height }),
          element("td", { text: label })
        ]
      })
    );
  }
  table.append(body);
  return table;
}

function provenanceSample(): HTMLElement {
  const list = element("dl", { className: "primitive-definition-list" });
  const fields = [
    ["제품 ID", "12345678"],
    ["업체", "코리아넷"],
    ["단가", "125,000원"],
    ["출처 상태", "조건 충족 시 자동선택"]
  ] as const;
  for (const [term, value] of fields) {
    list.append(
      element("div", {
        className: "primitive-definition",
        children: [
          element("dt", { text: term }),
          element("dd", { text: value })
        ]
      })
    );
  }
  return list;
}

export function renderPrimitiveShowcase(container: HTMLElement): void {
  const input = element("input", {
    attributes: {
      "aria-label": "품명 예시",
      "data-testid": "primitive-input",
      value: "CCTV 카메라"
    }
  });
  input.value = "CCTV 카메라";
  const primaryButton = element("button", {
    className: "button button-primary",
    text: "행 추가",
    attributes: { type: "button", "data-testid": "primitive-button" }
  });
  const secondaryButton = element("button", {
    className: "button button-secondary",
    text: "검토",
    attributes: { type: "button" }
  });

  const root = element("main", {
    className: "showcase",
    attributes: { "data-testid": "primitive-showcase" },
    children: [
      element("header", {
        className: "showcase-header",
        children: [
          element("p", {
            className: "showcase-kicker",
            text: "Concept A component gate"
          }),
          element("h1", { text: "견적 workbench primitive" }),
          element("p", {
            className: "showcase-summary",
            text: "각진 tonal layer와 고밀도 표, 상태 및 출처 표현을 확인함."
          })
        ]
      }),
      element("section", {
        className: "showcase-grid",
        attributes: { "aria-label": "컴포넌트 상태" },
        children: [
          element("article", {
            className: "primitive-panel",
            children: [
              element("h2", { text: "Control" }),
              element("label", {
                className: "field-label",
                text: "품명",
                children: [input]
              }),
              element("div", {
                className: "button-cluster",
                children: [primaryButton, secondaryButton]
              })
            ]
          }),
          element("article", {
            className: "primitive-panel",
            children: [
              element("h2", { text: "Density" }),
              showcaseTable()
            ]
          }),
          element("article", {
            className: "primitive-panel",
            children: [
              element("div", {
                className: "panel-title-row",
                children: [
                  element("h2", { text: "Provenance" }),
                  element("span", {
                    className: "status-badge status-badge-success",
                    text: "검증됨"
                  })
                ]
              }),
              provenanceSample()
            ]
          }),
          element("article", {
            className: "primitive-panel",
            children: [
              element("h2", { text: "Notice" }),
              element("p", {
                className: "notice legal-notice",
                text: DESIGN_CONTRACT.disclaimers.always,
                attributes: { "data-testid": "legal-notice" }
              }),
              element("p", {
                className: "notice unsigned-notice",
                text: DESIGN_CONTRACT.disclaimers.unsigned,
                attributes: { "data-testid": "unsigned-notice" }
              })
            ]
          })
        ]
      }),
      element("p", {
        className: "visually-hidden",
        attributes: { "aria-live": "polite" },
        text: "Primitive showcase 준비됨."
      })
    ]
  });
  container.replaceChildren(root);
}
