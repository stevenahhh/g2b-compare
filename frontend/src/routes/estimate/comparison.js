import { conciseSpec, documentItemName, documentUnit } from "../../lib/spec.js";
import { compactCompanyName } from "./formatting.js";

export const comparisonFor = (details, slot) =>
  details?.comparisons?.find((item) => item.slot === slot);
export const detailsFor = (remote, line) =>
  remote?.lines?.find((item) => item.id === line.id);
export function rowAttributes(
  document,
  remote,
  line,
  details = detailsFor(remote, line),
) {
  if (line.line_kind !== "option") return details?.attributes ?? [];
  if (!/카메라/u.test(line.item_name_snapshot)) return [];
  const index = document.lines.findIndex((item) => item.id === line.id);
  const main = document.lines
    .slice(0, index)
    .findLast((item) => item.line_kind === "main");
  return (
    detailsFor(remote, main ?? {})?.attributes ?? details?.attributes ?? []
  );
}
export function comparisonAttributes(
  document,
  remote,
  comparison,
  line,
  details,
) {
  if (line.line_kind === "option")
    return /카메라/u.test(line.item_name_snapshot)
      ? rowAttributes(document, remote, line, details)
      : [];
  return documentItemName(line.item_name_snapshot, line.spec_snapshot) ===
    line.item_name_snapshot
    ? (comparison.attributes ?? [])
    : [];
}
export function comparisonSpec(_document, _remote, comparison) {
  return comparison.spec_snapshot;
}
export const appliedPrice = (line, details) =>
  comparisonFor(details, "A")?.price_won_snapshot ??
  line.unit_price_won_snapshot;
export const tsvCell = (value) => {
  const normalized = String(value ?? "").replace(/[\t\r\n]+/g, " ");
  return /^\s*[=+\-@]/.test(normalized) ? `'${normalized}` : normalized;
};
const headers = [
  "품명",
  "규격",
  "단위",
  "적용단가",
  "A사 적용회사",
  "A사 규격",
  "A사 물품식별번호",
  "A사 단가",
  "B사 회사명",
  "B사 규격",
  "B사 물품식별번호",
  "B사 단가",
  "C사 회사명",
  "C사 규격",
  "C사 물품식별번호",
  "C사 단가",
  "비고",
];
export function tableTsv(document, remote) {
  const rows = [
    headers,
    ...(document?.lines ?? []).map((line) => {
      const details = detailsFor(remote, line);
      const comparisons = ["A", "B", "C"].flatMap((slot) => {
        const comparison = comparisonFor(details, slot);
        return comparison
          ? [
              compactCompanyName(comparison.company_snapshot),
              comparisonSpec(document, remote, comparison, line, details),
              comparison.product_id,
              comparison.price_won_snapshot,
            ]
          : ["", "", "", ""];
      });
      return [
        documentItemName(line.item_name_snapshot, line.spec_snapshot),
        conciseSpec(
          line.spec_snapshot,
          rowAttributes(document, remote, line, details),
          line.item_name_snapshot,
        ),
        documentUnit(
          line.item_name_snapshot,
          line.unit_snapshot,
          line.spec_snapshot,
        ),
        appliedPrice(line, details),
        ...comparisons,
        "",
      ];
    }),
  ];
  return rows.map((row) => row.map(tsvCell).join("\t")).join("\n");
}
