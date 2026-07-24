# Electron estimator Concept A design contract

This document fixes the renderer contract before UI implementation. It describes the exported `DESIGN_CONTRACT` in `src/renderer/design-contract.ts`; the JSON snapshot is generated from that value and must remain equal to it.

Contract identity is `contractId="electron-estimator.concept-a"` and `version=1`.

## Shell and density

- At 1440px, the shell is `224px` left rail, fluid center, and `320px` docked right inspector.
- At 1024px, the shell is `56px` left rail and fluid center. The inspector is a `360px` overlay.
- Total rows are sticky. Row heights are `26px` compact, `32px` regular, and `40px` comfortable.
- Center content and table regions scroll independently when their content exceeds the viewport.

## Type and color tokens

- Typeface is `Noto Sans KR`.
- Body text is `13px / 20px`; table text is `12px / 18px`.
- `background #F4F4F4`, `surface #FFFFFF`, `text #161616`, `secondary #525252`, `border #D9D9D9`.
- `accent #0F62FE`, `success #198038`, `warning #F1C21B`, `error #DA1E28`.

## Surfaces

Surfaces are square tonal layers. Radius is `0px`; gradients and rounded cards are forbidden. A surface may use the contract colors to establish hierarchy, but it must not introduce another visual treatment.

The machine-readable surface value is `shape="square-tonal"`; `gradient=false` and `roundedCards=false` are required.

## Keyboard, IME, focus, and accessibility

- Grid navigation recognizes `Tab`, `Shift+Tab`, `Enter`, `Escape`, and all four arrow keys.
- The keyboard state also includes `ArrowUp`, `ArrowDown`, `ArrowLeft`, and `ArrowRight`; `gridNavigation=true`.
- The IME state is `compositionStart="defer-validation"` and `compositionEnd="commit-and-validate"` so Korean composition is not interrupted.
- Focus is visible with a `3px` outline and is restored to the prior control after an inspector overlay closes.
- The focus state is `visible=true`, `outlinePx=3`, and `restoreAfterOverlayClose=true`.
- Primary controls are at least `44px`; the accessibility state is `primaryControlMinSizePx=44`, `liveRegion="aria-live"`, and `statusUpdates=true`.

## KoreaNet provenance state

KoreaNet selection requires specification pass, supplier-location evidence, and service-area evidence. Only eligible candidates may be selected; the lowest eligible price wins, joint-lowest ties remain explicit, and missing evidence blocks automatic selection. Each candidate exposes `productId`, `supplierName`, `unitPriceWon`, `unit`, `specSnapshot`, `sourceUrl`, `apiOperation`, `observedAt`, `sourcePayloadSha256`, `supplierLocationEvidence`, and `serviceAreaEvidence`.

## Required notices

The always-visible notice is `내부 비상업 검토용 · 법적 인증 아님 · 최신성 보장 없음`. Unsigned builds additionally show `주의: 코드 서명되지 않은 시험 빌드임. 운영체제가 배포자 신원을 검증하지 못함.`.

No UI implementation, responsive breakpoint beyond the two fixed desktop shells, gradients, rounded cards, dark mode, or animation is part of this contract.
