import { documentItemName, documentUnit } from "../../lib/spec.js";

export function localDocument(serverDocument) {
  return {
    id: serverDocument.id,
    title: serverDocument.title,
    lines: serverDocument.lines.map((line) => ({
      id: line.id,
      line_kind: line.line_kind,
      product_id: line.product_id,
      parent_product_id: line.parent_product_id,
      relation_id: line.relation_id,
      offer_operation: line.offer_operation,
      offer_key: line.offer_key,
      item_name_snapshot: line.item_name_snapshot,
      spec_snapshot: line.spec_snapshot,
      company_snapshot: line.company_snapshot,
      unit_snapshot: line.unit_snapshot,
      unit_price_won_snapshot: line.unit_price_won_snapshot,
      quantity: String(line.quantity),
    })),
  };
}

export function appendDocumentLine(document, item, createId) {
  if (document.lines.length >= 9)
    return { document, error: "문서에는 품목을 최대 9개까지 추가할 수 있음." };
  if (
    item.relation_id &&
    document.lines.some((line) => line.relation_id === item.relation_id)
  )
    return { document, error: "이미 추가된 하위 품목임." };
  const line = {
    id: createId(),
    line_kind: item.relation_id ? "option" : "main",
    product_id: item.product_id,
    parent_product_id: item.parent_product_id ?? null,
    relation_id: item.relation_id ?? null,
    offer_operation: null,
    offer_key: null,
    item_name_snapshot: documentItemName(item.name, item.spec),
    spec_snapshot: item.spec,
    company_snapshot: item.company_name,
    unit_snapshot: documentUnit(item.name, item.unit, item.spec),
    unit_price_won_snapshot: item.price_won,
    quantity: "1",
  };
  return {
    document: { ...document, lines: [...document.lines, line] },
    error: "",
  };
}

export function removeDocumentLine(document, lineId) {
  return {
    ...document,
    lines: document.lines.filter((line) => line.id !== lineId),
  };
}
