# G2B 유사물품 비교 UI

## 0. 목적
로컬의 검증된 릴리스만 읽어 빠르게 검색하고 비교함.

## 1. 방향
Layer A minimalist, Linear precision, data-dense light를 기준으로 삼음.

## 2. 색상
본문 `#0F172A`, 강조 `#0369A1`, 배경 `#F8FAFC`, 경계 `#E2E8F0`.

## 3. 글꼴
시스템 CJK 글꼴만 사용하며 모든 요소의 굵기는 400으로 고정함.

## 4. 레이아웃
1280px에서는 좌측 검색 조건과 우측 결과 표를 사용함. 768px 이하에서는 단일 열, 375px에서는 표를 카드형 행으로 읽을 수 있게 함.

## 5. 상호작용
기본 GET 제출이 항상 동작함. JavaScript가 있으면 같은 URL을 fetch하고 기존 결과를 유지한 채 교체함.

## 6. 접근성
건너뛰기 링크, 시맨틱 랜드마크, 44px 입력 높이, 명확한 포커스, `aria-live`, reduced-motion을 적용함.

## 7. 상태
primary state는 하나만 노출하고 보조 상태는 정렬된 토큰으로 병행 표시함.

## 8. 조사 기록
계획의 embedded references와 ui-ux-db 결과를 반영함. lazyweb은 `AUTH_REQUIRED`로 화면 0개였음. 사용자 요청이 이미지 미사용이므로 image draft는 생략함.
