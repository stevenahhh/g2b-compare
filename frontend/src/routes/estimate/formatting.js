export const OPTION_GROUPS = [
  ["selection", "선택품목"],
  ["additional", "추가선택품목"],
  ["construction", "공사"],
];
export const money = (value) => Number(value ?? 0).toLocaleString();

export function newId() {
  return [...crypto.getRandomValues(new Uint8Array(16))]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

export function compactCompanyName(value) {
  return String(value ?? "")
    .replace(/^(?:주식회사|\(주\)|㈜)\s*/u, "")
    .trim();
}

export function productTitle(item) {
  const parts = String(item.spec ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const purpose =
    item.attributes?.find((attribute) => attribute.name === "용도")?.value ??
    (parts.length > 3 ? parts.at(-1) : "");
  return [
    ...new Set(
      [
        item.name,
        parts[1] || compactCompanyName(item.company_name),
        parts[2],
        purpose,
      ].filter(Boolean),
    ),
  ].join(", ");
}

export function optionGroup(item) {
  if (/공사/u.test(`${item.name} ${item.spec}`)) return "construction";
  return item.relation_kind === "component" ? "selection" : "additional";
}
