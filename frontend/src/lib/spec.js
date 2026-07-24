export function conciseSpec(spec, attributes = [], itemName = "") {
  const values = attributes.map((attribute) => String(attribute.value ?? "").trim()).filter(Boolean);
  const details = values.join(" ");
  const rawSpec = String(spec ?? "");
  const matchText = `${details} ${rawSpec}`;
  const name = documentItemName(itemName || rawSpec.split(",")[0]?.trim(), rawSpec);
  const optionSpec = rawSpec
    .replace(/^\[[^\]]+\]\s*\[\d{8}\]\s*[^,]+,\s*/u, "")
    .replace(/\s*:\s*[\d,]+\s*$/u, "")
    .trim();
  if (optionSpec !== rawSpec.trim()) return optionSpec;
  const kind = attributes.find((attribute) => attribute.name === "종류")?.value;
  if (kind) return kind;
  if (/영상감시장치|보안용카메라/u.test(name)) {
    const shape = /PTZ|회전|스피드돔/iu.test(details) ? "회전형" : "고정형";
    const megapixels = details.match(/(\d+(?:\.\d+)?)\s*MP/iu)?.[1];
    const resolution = details.match(/(\d+(?:\.\d+)?)\s*만화소/u)?.[1]
      ?? (megapixels ? String(Number(megapixels) * 100) : "");
    const zoom = details.match(/(?:광학\s*|Optical\s*x\s*)(\d+(?:\.\d+)?)\s*배?줌?/iu)?.[1]
      ?? details.match(/(\d+(?:\.\d+)?)\s*배줌/u)?.[1];
    return [shape, resolution && `${resolution}만화소`, zoom && `${zoom}배줌`].filter(Boolean).join(", ");
  }
  const channel = matchText.match(/(\d+)\s*ch/iu)?.[1]
    ?? matchText.match(/(?:NVR|EM)\s*-?\s*[^0-9]{0,3}(\d+)/iu)?.[1];
  if (/비디오레코더|NVR|DVR/iu.test(name) && channel) return `${channel}ch`;
  const port = matchText.match(/(\d+)\s*port/iu)?.[1];
  if (/스위치|허브/iu.test(name) && port) {
    const poe = /PoE|\b[^,\s]*PG[^,\s]*/iu.test(matchText);
    return `${port}port${poe ? " PoE" : ""}`;
  }
  const capacity = matchText.match(/(\d+(?:\.\d+)?)\s*TB/iu)?.[1];
  if (/하드디스크|저장장치/iu.test(name) && capacity) return `${capacity}TB`;
  if (values.length) return values.slice(0, 3).join(", ");
  const parts = rawSpec.split(",").map((part) => part.trim()).filter(Boolean);
  return parts.length > 3 ? parts.slice(3).join(", ") : parts.at(-1) ?? "";
}

export function documentItemName(itemName, spec = "") {
  const name = String(itemName ?? "");
  if (!/^(?:추가선택품목|선택품목|옵션)$/u.test(name)) return name;
  return String(spec).match(/^\[[^\]]+\]\s*\[\d{8}\]\s*([^,]+)/u)?.[1]?.trim() || name;
}

export function documentUnit(itemName, sourceUnit, spec = "") {
  const name = documentItemName(itemName, spec);
  if (/보안용카메라|디지털비디오레코더|네트워크스위치/u.test(name)) return "대";
  if (/난연전력케이블|UTP케이블/u.test(name)) return "M";
  if (/정보통신공사/u.test(name)) return "식";
  return sourceUnit;
}
