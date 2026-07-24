export const OOXML_PATCH_ERROR_CODES = [
  "OOXML_CELL_NOT_OWNED",
  "PROFILE_CAPACITY_EXCEEDED",
  "STALE_SOURCE",
  "PATCH_VALUE_INVALID"
] as const;

export type OoxmlPatchErrorCode =
  (typeof OOXML_PATCH_ERROR_CODES)[number];

const ERROR_MESSAGES = {
  OOXML_CELL_NOT_OWNED: "앱 소유 셀이 아니어서 변경할 수 없음.",
  PROFILE_CAPACITY_EXCEEDED: "원본 양식의 품목 용량을 초과함.",
  STALE_SOURCE: "선택한 원본 파일이 예상 원본과 다름.",
  PATCH_VALUE_INVALID: "셀에 쓸 값 형식이 올바르지 않음."
} as const satisfies Readonly<Record<OoxmlPatchErrorCode, string>>;

export class OoxmlPatchError extends Error {
  readonly name = "OoxmlPatchError";

  constructor(readonly code: OoxmlPatchErrorCode) {
    super(ERROR_MESSAGES[code]);
    delete this.stack;
  }
}

