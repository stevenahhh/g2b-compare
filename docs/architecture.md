# Architecture

## 실행 흐름

1. 검증된 API 계약과 호출 한도를 읽음.
2. operation별 날짜 구간과 페이지를 순서대로 수집함.
3. 요청 지문, 원문 SHA-256, 호출 ledger, 다음 페이지 cursor를 SQLite에 저장함.
4. operation의 모든 페이지가 연속적으로 검증된 경우에만 source snapshot을 게시함.
5. 개별 속성과 승인된 XLSX 관계를 별도 provenance로 결합함.
6. product, offer, attribute를 materialization snapshot으로 만듦.
7. exact membership, FTS5 recall, TF-IDF index와 비교 3-slot cache를 생성함.
8. 모든 구성요소가 일치할 때만 `active_release`를 원자적으로 교체함.
9. FastAPI 웹 앱은 active release를 읽기 전용으로 검색함.

## 우선조달 상품 설명 보강

현재 수집된 본품 `priority_products` 27,757행은 모두 `product_id`와
`ctrtItemMngNo`가 든 정규 상세 페이지 URL을 가짐. 설명 보강은 일반 앱 실행과
분리된 명시적 `g2b-priority crawl-details` 작업임. 작업마다 Playwright 브라우저
하나를 임시로 열어 공개 SSO 쿠키를 만든 뒤, 같은 세션에서 관찰된 WebSquare
endpoint로 고정된 POST를 직접 보냄. 브라우저와 쿠키는 작업이 끝나면 폐기함.

응답은 2,000,000바이트로 제한함. 정상 계약의 exact JSON bytes와 실패 때 수신한
bounded body는 `.g2b/raw`에 content-addressed gzip으로 보존함. 파싱 결과와
`stored`, `missing`, `failed`
관찰은 append-only로 쌓고, 상품별 최신 pointer만 같은 transaction에서 바꿈.
이 경로는 기존 `priority_products.raw_json`을 덮어쓰지 않음.

이 endpoint는 공식 OpenAPI가 아니라 종합쇼핑몰 사이트에서 관찰한 계약임.
인증, 응답 schema, 429 문제가 생기면 새 작업 dispatch를 멈춰 사이트 변경이나
호출 제한을 먼저 확인하게 함.

## Tauri 데스크톱 견적 저장 경계

Tauri 데스크톱은 사용자 AppData의 `g2b.sqlite3`를 읽으며, 견적에 대해서는 이
DB만 권위 저장소로 사용함. 견적 생성, 조회, 수정, 삭제와 비교군 새로고침은 Rust
명령이 이 DB에서 트랜잭션으로 처리함. 성공한 명령은 네트워크 상태와 관계없이
최종 저장 결과이며, 후속 서버 승인을 기다리지 않음.

일반 견적 CRUD는 `offline-replay.sqlite3`에 항목을 추가하지 않음. 이 별도 DB는
가져온 변경이나 중단된 복구 작업만 보관하는 recovery journal임. replay는 해당
변경을 현재 저장 revision과 대조해 `g2b.sqlite3`에 순서대로 materialize함. 적용된
항목은 같은 변경을 다시 만들지 않도록 확인 처리하며, 충돌하거나 실패한 항목은
명시적으로 해결하거나 다시 시도할 때까지 보존함.

다른 데스크톱 창이나 프로세스가 보낸 saved/deleted 이벤트는 현재 저장 내용을
다시 읽게 하는 신호임. 이벤트 자체는 별도 권위가 아니며, 편집기의 저장되지 않은
변경을 덮어쓰면 안 됨. 결정 근거는
[ADR 0001](adr/0001-tauri-local-estimate-authority.md)에 기록함.

## 경계

- 네트워크 접근은 contract capture, sync, 명시적 상품 설명 보강에만 있음.
- 검색, 비교, 견적 등 일반 앱 경로는 SQLite와 로컬 index만 사용하는
  offline-only 경로임.
- 상품 설명을 앱에 연결할 때는 정규화된 `detail_text`만 노출하고 렌더링해야
  하며, provider HTML인 `decoded_html`은 노출하거나 렌더링하지 않음.
- 원문 payload는 content-addressed gzip 파일로 보존함.
- active source, materialization, index, relation, cache는 서로 다른 snapshot ID를
  가지며 release가 정확한 조합을 고정함.
- 실패한 build나 부분 sync는 기존 active release를 바꾸지 않음.
- 추가선택품목 관계는 승인된 workbook 근거만 사용하고 API 동시 출현으로
  부모 관계를 추론하지 않음.

## 주요 모듈

| 경로 | 책임 |
|---|---|
| `contracts/` | 공식 endpoint, schema, quota 계약 |
| `sources/` | HTTP 응답과 envelope parsing |
| `priority_description*.py` | 공개 SSO bootstrap, 설명 POST, 파싱, 재개, 관찰 저장 |
| `sync/` | window 계획, pagination, checkpoint, publish |
| `materialize/` | 제품·가격·속성·옵션 역할 정규화 |
| `search/` | exact membership, FTS5, TF-IDF index |
| `ranking/` | 규격·가격 feature와 3-slot 순위 |
| `services/` | 검색·비교 use case와 release 읽기 |
| `web/` | 레거시 웹 UI와 상태 표시 |
| `desktop/src/` | Tauri 데스크톱 화면과 현재 편집 상태 |
| `desktop/src-tauri/src/estimate/` | `g2b.sqlite3` 견적 CRUD와 비교군 새로고침 |
| `desktop/src-tauri/src/offline_replay.rs` | 가져오기와 복구 변경의 exact-once materialization |
| `observability/` | CLI, health, readiness, 비밀검사 |
