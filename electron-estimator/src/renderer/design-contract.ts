export const DESIGN_CONTRACT = {
  contractId: "electron-estimator.concept-a",
  version: 1,
  layout: {
    viewport1440: {
      viewportWidthPx: 1440,
      leftRailPx: 224,
      center: "fluid",
      rightInspectorPx: 320,
      inspectorMode: "docked",
    },
    viewport1024: {
      viewportWidthPx: 1024,
      leftRailPx: 56,
      center: "fluid",
      inspectorMode: "overlay",
      overlayInspectorPx: 360,
    },
    rowHeightsPx: {
      compact: 26,
      regular: 32,
      comfortable: 40,
    },
    stickyTotals: true,
  },
  typography: {
    fontFamily: "Noto Sans KR",
    body: { fontSizePx: 13, lineHeightPx: 20 },
    table: { fontSizePx: 12, lineHeightPx: 18 },
  },
  colors: {
    background: "#F4F4F4",
    surface: "#FFFFFF",
    text: "#161616",
    secondary: "#525252",
    border: "#D9D9D9",
    accent: "#0F62FE",
    success: "#198038",
    warning: "#F1C21B",
    error: "#DA1E28",
  },
  surface: {
    shape: "square-tonal",
    radiusPx: 0,
    gradient: false,
    roundedCards: false,
  },
  interaction: {
    keyboard: {
      keys: [
        "Tab",
        "Shift+Tab",
        "Enter",
        "Escape",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
      ],
      gridNavigation: true,
    },
    ime: {
      compositionStart: "defer-validation",
      compositionEnd: "commit-and-validate",
    },
    focus: {
      visible: true,
      outlinePx: 3,
      restoreAfterOverlayClose: true,
    },
    accessibility: {
      primaryControlMinSizePx: 44,
      liveRegion: "aria-live",
      statusUpdates: true,
    },
  },
  provenance: {
    koreaNet: {
      selection: {
        requiresSpecPass: true,
        requiresSupplierLocationEvidence: true,
        requiresServiceAreaEvidence: true,
        chooseLowestEligiblePrice: true,
        tiesChooseJointLowest: true,
        noAutomaticSelectionWithoutEvidence: true,
      },
      requiredFields: [
        "productId",
        "supplierName",
        "unitPriceWon",
        "unit",
        "specSnapshot",
        "sourceUrl",
        "apiOperation",
        "observedAt",
        "sourcePayloadSha256",
        "supplierLocationEvidence",
        "serviceAreaEvidence",
      ],
    },
  },
  disclaimers: {
    always: "내부 비상업 검토용 · 법적 인증 아님 · 최신성 보장 없음",
    unsigned:
      "주의: 코드 서명되지 않은 시험 빌드임. 운영체제가 배포자 신원을 검증하지 못함.",
  },
} as const;

export type DesignContract = typeof DESIGN_CONTRACT;
