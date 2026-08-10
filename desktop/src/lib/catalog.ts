import type {
  CatalogPage,
  CatalogProduct,
  CatalogSort,
  CatalogViewState,
  RelationCategory,
} from "./models";

export const PAGE_SIZE = 30;
export const PREFERRED_COMPANY = "주식회사 코리아넷";
export const PRODUCT_ROW_HEIGHT = 188;
export const PRODUCT_VIEWPORT_HEIGHT = 600;
export const OPTION_ROW_HEIGHT = 112;
export const OPTION_VIEWPORT_HEIGHT = 520;
export const OVERSCAN = 4;

export function emptyPage<T>(): CatalogPage<T> {
  return { items: [], page: 1, page_count: 1, total_count: 0 };
}

export function mergePage<T>(
  previous: CatalogPage<T>,
  incoming: CatalogPage<T>,
  requestedPage: number,
  identity: (item: T) => string,
): CatalogPage<T> {
  const before = requestedPage === 1 ? [] : previous.items;
  const ids = new Set(before.map(identity));
  return {
    ...incoming,
    items: [...before, ...incoming.items.filter((item) => !ids.has(identity(item)))],
  };
}

export interface VirtualWindow<T> {
  items: T[];
  top: number;
  bottom: number;
}

export function virtualWindow<T>(
  items: T[],
  scrollTop: number,
  rowHeight: number,
  viewportHeight: number,
  overscan = OVERSCAN,
): VirtualWindow<T> {
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(
    items.length,
    start + Math.ceil(viewportHeight / rowHeight) + overscan * 2,
  );
  return {
    items: items.slice(start, end),
    top: start * rowHeight,
    bottom: (items.length - end) * rowHeight,
  };
}

export function productTitle(item: CatalogProduct): string {
  const specParts = item.spec
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const compactCompany = item.company_name
    .replace(/^(?:주식회사|\(주\)|㈜)\s*/u, "")
    .trim();
  const purpose =
    item.attributes?.find((attribute) => attribute.name === "용도")?.value ??
    (specParts.length > 3 ? specParts.at(-1) : "");
  return [item.name, specParts[1] || compactCompany, specParts[2], purpose]
    .filter((value, index, values) => Boolean(value) && values.indexOf(value) === index)
    .join(", ");
}

export function relationIdentity(item: {
  relation_id?: string;
  parent_product_id: string;
  product_id: string;
  category: RelationCategory;
}): string {
  return item.relation_id ?? `${item.parent_product_id}:${item.category}:${item.product_id}`;
}

export function defaultCatalogView(): CatalogViewState {
  return {
    query: "",
    sort: "price_asc",
    page: 1,
    selected_product_id: null,
    active_category: "selection",
    product_scroll_top: 0,
    relation_scroll_top: {
      selection: 0,
      additional: 0,
      construction: 0,
    },
    relation_query: { selection: "", additional: "", construction: "" },
    relation_page: { selection: 1, additional: 1, construction: 1 },
  };
}

export function isCatalogSort(value: unknown): value is CatalogSort {
  return ["price_asc", "price_desc", "name_asc", "product_id_asc"].includes(
    String(value),
  );
}
