import { element } from "../../renderer/dom.js";
import type {
  MarketPriceRow,
  ProductivityRow
} from "../../official/schemas.js";
import type { NativeViewOptions } from "./view-types.js";

type CatalogMatch =
  | { readonly kind: "market"; readonly row: MarketPriceRow }
  | { readonly kind: "productivity"; readonly row: ProductivityRow };

export function createCatalog(options: NativeViewOptions): HTMLElement {
  const search = element("input", {
    attributes: {
      type: "search",
      placeholder: "공식 시장단가·표준품셈 검색",
      "aria-label": "공식 카탈로그 검색",
      "data-testid": "catalog-search"
    }
  });
  search.value = options.state.catalogQuery;
  search.addEventListener("input", () => {
    options.state.catalogQuery = search.value;
    options.events.rerender(true);
  });
  const list = element("div", {
    className: "catalog-results",
    attributes: { "data-testid": "catalog-results" }
  });
  if (options.state.catalog === null) {
    list.append(element("p", { text: "공식 카탈로그 확인 중임." }));
  } else {
    matches(options).forEach((match) => {
      list.append(createResult(options, match));
    });
  }
  return element("section", {
    className: "native-catalog",
    children: [
      element("div", {
        className: "catalog-toolbar",
        children: [
          search,
          button("빈 행 추가", "add-row", options.events.addRow)
        ]
      }),
      list
    ]
  });
}

function matches(options: NativeViewOptions): readonly CatalogMatch[] {
  const catalog = options.state.catalog;
  if (catalog === null) {
    return [];
  }
  const query = options.state.catalogQuery.trim().toLocaleLowerCase("ko-KR");
  if (query.length === 0) {
    return [];
  }
  const market = catalog.marketPrices
    .filter((row) =>
      `${row.category} ${row.name} ${row.specification} ${row.work_code}`
        .toLocaleLowerCase("ko-KR")
        .includes(query)
    )
    .slice(0, 6)
    .map((row) => ({ kind: "market", row }) satisfies CatalogMatch);
  const productivity = catalog.productivity
    .filter((row) =>
      `${row.category} ${row.task} ${row.specification} ${row.standard_item}`
        .toLocaleLowerCase("ko-KR")
        .includes(query)
    )
    .slice(0, 6)
    .map((row) => ({ kind: "productivity", row }) satisfies CatalogMatch);
  return [...market, ...productivity];
}

function createResult(
  options: NativeViewOptions,
  match: CatalogMatch
): HTMLElement {
  const market = match.kind === "market";
  const title = market ? match.row.name : match.row.task;
  const description = market
    ? `${match.row.specification} · ${match.row.unit} · ${match.row.unit_price_krw.toLocaleString("ko-KR")}원`
    : `${match.row.specification} · ${match.row.unit} · ${match.row.standard_item}`;
  const add = button("새 행 추가", "", () => {
    if (match.kind === "market") {
      options.events.addMarket(match.row, "new");
    } else {
      options.events.addProductivity(match.row, "new");
    }
  });
  add.setAttribute("data-catalog-kind", match.kind);
  const apply = button("선택 행에 적용", "", () => {
    if (match.kind === "market") {
      options.events.addMarket(match.row, "selected");
    } else {
      options.events.addProductivity(match.row, "selected");
    }
  });
  apply.setAttribute("data-catalog-apply", match.kind);
  return element("article", {
    className: "catalog-result",
    children: [
      element("div", {
        children: [
          element("strong", { text: title }),
          element("p", { text: description })
        ]
      }),
      element("div", { className: "catalog-actions", children: [add, apply] })
    ]
  });
}

function button(
  text: string,
  testId: string,
  action: () => void
): HTMLButtonElement {
  const attributes: Record<string, string> = { type: "button" };
  if (testId.length > 0) {
    attributes["data-testid"] = testId;
  }
  const node = element("button", {
    className: "button button-secondary",
    text,
    attributes
  });
  node.addEventListener("click", action);
  return node;
}
