import type { SourcedProductObservation } from "../official/schemas.js";
import { element } from "./dom.js";
import {
  SELECTION_REASON_LABELS,
  type WorkbenchRow
} from "./workbench-model.js";

const number = new Intl.NumberFormat("ko-KR");

function definition(
  label: string,
  value: string,
  attribute: "data-provenance-field" | "data-evidence-field"
): HTMLElement {
  return element("div", {
    className: "inspector-definition",
    attributes: { [attribute]: label },
    children: [
      element("dt", { text: label }),
      element("dd", { text: value })
    ]
  });
}

function sourceDefinitions(source: SourcedProductObservation): HTMLElement {
  const list = element("dl", { className: "inspector-definitions" });
  const fields = [
    ["제품 ID", source.product_id],
    ["업체", source.supplier_name],
    ["단가", `${number.format(source.unit_price_won)}원`],
    ["단위", source.unit],
    ["규격 snapshot", source.spec_snapshot],
    ["Source URL", source.source_url],
    ["API operation", source.api_operation],
    ["Observed time", source.observed_at],
    ["Payload SHA-256", source.source_payload_sha256]
  ] as const;
  for (const [label, value] of fields) {
    list.append(definition(label, value, "data-provenance-field"));
  }
  return list;
}

function evidenceDefinitions(source: SourcedProductObservation): HTMLElement {
  const list = element("dl", {
    className: "inspector-evidence",
    attributes: { "aria-label": "지역 및 서비스 근거" }
  });
  list.append(
    definition(
      "Supplier location evidence",
      source.supplier_location_evidence?.statement ?? "확인된 근거 없음",
      "data-evidence-field"
    ),
    definition(
      "Service area evidence",
      source.service_area_evidence?.statement ?? "확인된 근거 없음",
      "data-evidence-field"
    )
  );
  return list;
}

export function createInspector(
  row: WorkbenchRow,
  narrow: boolean,
  isOpen: boolean,
  close: () => void
): HTMLElement {
  const visible = !narrow || isOpen;
  const title = element("h2", {
    text: "출처 및 계산 근거",
    attributes: { "data-testid": "selected-line-name" }
  });
  title.append(element("span", { className: "selected-line", text: row.itemName }));
  const heading = element("div", {
    className: "inspector-heading",
    children: [title]
  });
  if (row.selection?.kind === "selected") {
    heading.append(
      element("span", {
        className: "status-badge status-badge-success",
        text: "KoreaNet 자동선택",
        attributes: { "data-testid": "koreanet-badge" }
      })
    );
  }
  if (narrow) {
    const closeButton = element("button", {
      className: "inspector-close",
      text: "닫기",
      attributes: {
        type: "button",
        "data-testid": "close-inspector",
        "aria-label": "출처 inspector 닫기"
      }
    });
    closeButton.addEventListener("click", close);
    heading.append(closeButton);
  }

  const body = element("div", { className: "inspector-body" });
  body.append(
    element("section", {
      className: "calculation-summary",
      children: [
        element("h3", { text: "계산 방식" }),
        element("p", { text: row.method }),
        element("p", {
          className: "selection-reason",
          text:
            row.selection === null
              ? "자동선택 판정 없음"
              : SELECTION_REASON_LABELS[row.selection.reason],
          attributes: { "data-testid": "selection-reason" }
        })
      ]
    })
  );
  if (row.source === null) {
    body.append(
      element("section", {
        className: "empty-source",
        attributes: { "data-testid": "empty-source" },
        children: [
          element("h3", { text: "연결된 출처 없음" }),
          element("p", {
            text: "사용자 입력값임. 자동선택, 최신성 또는 법적 효력을 주장하지 않음."
          })
        ]
      })
    );
  } else {
    body.append(sourceDefinitions(row.source), evidenceDefinitions(row.source));
  }

  return element("aside", {
    className: `provenance-inspector${visible ? " is-open" : ""}`,
    attributes: {
      ...(narrow
        ? { role: "dialog", "aria-modal": "true" }
        : { role: "complementary" }),
      "data-testid": "provenance-inspector",
      "aria-label": "선택 행 출처 inspector",
      "aria-hidden": String(!visible),
      tabindex: "-1"
    },
    children: [heading, body]
  });
}
