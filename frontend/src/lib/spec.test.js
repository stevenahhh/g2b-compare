import { describe, expect, it } from "vitest";
import { conciseSpec, documentItemName, documentUnit } from "./spec.js";

describe("conciseSpec", () => {
  it("removes the option label and price from an additional item specification", () => {
    expect(conciseSpec(
      "[별도구매] [20683697] 난연접지용비닐절연전선, F-GV, 6㎟ : 2,050",
      [{ name: "옵션/기타", value: "카메라:200만화소/광학4배줌" }],
      "추가선택품목",
    )).toBe("F-GV, 6㎟");
  });

  it.each([
    ["영상감시장치", "영상감시장치, 코리아넷, MODEL, 방범감시시스템", [
      { name: "구성", value: "Bullet카메라:KN-B3204U6R" },
      { name: "옵션/기타", value: "Bullet카메라:200만화소/광학4배줌" },
    ], "고정형, 200만화소, 4배줌"],
    ["보안용카메라", "KN-B3204U6R, 12.7mmCMOS", [
      { name: "구성", value: "Bullet카메라:KN-B3204U6R" },
      { name: "옵션/기타", value: "Bullet카메라:200만화소/광학4배줌" },
    ], "고정형, 200만화소, 4배줌"],
    ["디지털비디오레코더", "EM-16B8V2, 16GB", [], "16ch"],
    ["네트워크스위치", "MV-PG2404M, 24port", [], "24port PoE"],
    ["하드디스크드라이브", "6TB", [], "6TB"],
  ])("formats %s like the unit-price sheet", (name, spec, attributes, expected) => {
    expect(conciseSpec(spec, attributes, name)).toBe(expected);
  });

  it.each([
    ["보안용카메라", "개", "대"],
    ["디지털비디오레코더", "개", "대"],
    ["네트워크스위치", "개", "대"],
    ["하드디스크드라이브", "개", "개"],
    ["난연전력케이블", "개", "M"],
    ["UTP케이블", "개", "M"],
    ["정보통신공사", "개", "식"],
  ])("uses the unit-price sheet unit for %s", (name, source, expected) => {
    expect(documentUnit(name, source)).toBe(expected);
  });

  it("derives an additional item's name and unit from its source label", () => {
    const spec = "[별도구매] [22067194] UTP케이블, CAT.5E/CM 4P : 2,740";
    expect(documentItemName("추가선택품목", spec)).toBe("UTP케이블");
    expect(documentUnit("추가선택품목", "개", spec)).toBe("M");
  });
});
