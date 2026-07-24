import { calculateNativeWorkbook } from "../../native/calculation.js";
import {
  NativeWorkbookError,
  parseNativeWorkbookInput,
  type NativeWorkbookInput
} from "../../native/input.js";
import type { NativeProjectWire } from "./contracts.js";
import type { NativeWorkflowState } from "./state.js";
import { buildWireLine } from "./validation-costs.js";

export const NATIVE_ERROR_MESSAGES = {
  REQUIRED_FIELD: "오류 REQUIRED_FIELD: 프로젝트와 행의 필수값을 입력해야 함.",
  NON_POSITIVE_INPUT: "오류 NON_POSITIVE_INPUT: 수량과 단가는 0보다 커야 함.",
  SOURCE_REQUIRED: "오류 SOURCE_REQUIRED: 적용단가의 출처를 입력해야 함.",
  RATE_CONTEXT_REQUIRED:
    "오류 RATE_CONTEXT_REQUIRED: 공식단가에 필요한 요율 문맥을 모두 입력해야 함.",
  PRICING_METHOD_CONFLICT:
    "오류 PRICING_METHOD_CONFLICT: 시장단가와 표준품셈을 한 행에 동시에 적용할 수 없음.",
  STALE_SELECTOR:
    "오류 STALE_SELECTOR: 행이 변경되어 Task8 선택을 다시 실행해야 함.",
  INVALID_INPUT: "오류 INVALID_INPUT: 입력 형식과 출처 연결을 확인해야 함.",
  NATIVE_CAPACITY_EXCEEDED:
    "오류 NATIVE_CAPACITY_EXCEEDED: 품목은 최대 200행까지 입력할 수 있음.",
  KOREANET_SELECTION_CONFLICT:
    "오류 KOREANET_SELECTION_CONFLICT: Task8 선택 결과와 행 출처가 일치하지 않음.",
  STALE_PROVENANCE:
    "오류 STALE_PROVENANCE: 공식 데이터 버전이 현재 고정본과 일치하지 않음."
} as const;

export type NativeErrorCode = keyof typeof NATIVE_ERROR_MESSAGES;
export type NativeValidationResult =
  | {
      readonly ok: true;
      readonly wire: NativeProjectWire;
      readonly parsed: NativeWorkbookInput;
      readonly calculation: ReturnType<typeof calculateNativeWorkbook>;
    }
  | {
      readonly ok: false;
      readonly codes: readonly NativeErrorCode[];
      readonly messages: readonly string[];
    };

export function validateNativeWorkflow(
  state: NativeWorkflowState
): NativeValidationResult {
  const codes = new Set<NativeErrorCode>();
  if (
    state.projectId.trim().length === 0 ||
    state.projectName.trim().length === 0 ||
    state.preparedOn.length === 0 ||
    state.rows.length === 0
  ) {
    codes.add("REQUIRED_FIELD");
  }
  const lines = state.rows.flatMap((row) => {
    const line = buildWireLine(state, row, codes);
    return line === null ? [] : [{ field: row.field, line }];
  });
  const wire = {
    projectId: state.projectId,
    projectName: state.projectName,
    preparedOn: state.preparedOn,
    lines,
    koreaNetSelections: state.rows.flatMap((row) =>
      row.selection === null ? [] : [{ lineId: row.id, result: row.selection }]
    )
  };
  if (codes.size > 0) {
    return invalid(codes);
  }
  try {
    const parsed = parseNativeWorkbookInput(wire);
    return {
      ok: true,
      wire,
      parsed,
      calculation: calculateNativeWorkbook(parsed)
    };
  } catch (error) {
    if (error instanceof NativeWorkbookError) {
      const code = error.code;
      codes.add(
        code === "PRICING_METHOD_CONFLICT" ||
          code === "NATIVE_CAPACITY_EXCEEDED" ||
          code === "KOREANET_SELECTION_CONFLICT" ||
          code === "STALE_PROVENANCE"
          ? code
          : "INVALID_INPUT"
      );
      return invalid(codes);
    }
    throw error;
  }
}

function invalid(codes: Set<NativeErrorCode>): NativeValidationResult {
  const ordered = [...codes];
  return {
    ok: false,
    codes: ordered,
    messages: ordered.map((code) => NATIVE_ERROR_MESSAGES[code])
  };
}
