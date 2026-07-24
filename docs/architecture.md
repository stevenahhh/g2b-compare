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

## 경계

- 네트워크 접근은 contract capture와 sync에만 있음.
- 검색과 비교는 SQLite와 로컬 index만 사용함.
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
| `sync/` | window 계획, pagination, checkpoint, publish |
| `materialize/` | 제품·가격·속성·옵션 역할 정규화 |
| `search/` | exact membership, FTS5, TF-IDF index |
| `ranking/` | 규격·가격 feature와 3-slot 순위 |
| `services/` | 검색·비교 use case와 release 읽기 |
| `web/` | 데스크톱 웹 UI와 상태 표시 |
| `observability/` | CLI, health, readiness, 비밀검사 |
