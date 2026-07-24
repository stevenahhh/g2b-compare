export const LEGACY_IMPORT_ERROR_CODES = [
  "UNSUPPORTED_WORKBOOK",
  "CORRUPT_OOXML",
  "UNSAFE_ZIP_ENTRY",
  "ZIP_LIMIT_EXCEEDED",
  "STALE_PROFILE"
] as const;

export type LegacyImportErrorCode =
  (typeof LEGACY_IMPORT_ERROR_CODES)[number];

const ERROR_MESSAGES = {
  UNSUPPORTED_WORKBOOK: "지원하지 않는 원본 파일임.",
  CORRUPT_OOXML: "손상된 OOXML 파일임.",
  UNSAFE_ZIP_ENTRY: "안전하지 않은 ZIP 항목이 있음.",
  ZIP_LIMIT_EXCEEDED: "OOXML 패키지 안전 한도를 초과함.",
  STALE_PROFILE: "원본 프로필 정보가 일치하지 않음."
} as const satisfies Readonly<Record<LegacyImportErrorCode, string>>;

export class LegacyImportError extends Error {
  readonly name = "LegacyImportError";

  constructor(readonly code: LegacyImportErrorCode) {
    super(ERROR_MESSAGES[code]);
    delete this.stack;
  }
}
