# Data dictionary

## 런타임 파일

| 경로 | 내용 |
|---|---|
| `.g2b/g2b.sqlite3` | sync, snapshot, release, cache 메타데이터 |
| `.g2b/raw/` | SHA-256로 주소화된 gzip 원문 응답, 압축 해제하면 수신한 exact bytes와 일치 |
| `.g2b/docs/api-contract-observed.json` | 런타임에서 사용하는 검증 API 계약 |
| `.g2b/releases/current/` | 게시된 release DB와 검색 index |

## 수집과 provenance

| 테이블 | 내용 |
|---|---|
| `api_call_ledger` | operation별 예약·HTTP 결과·rolling quota 사용량 |
| `sync_runs` | full/delta 실행 상태와 다음 page cursor |
| `sync_windows` | 실행에 고정된 날짜 구간 |
| `request_manifests` | 인증키를 제외한 요청 파라미터와 지문 |
| `raw_blobs` | 원문 SHA, 파일 경로, Content-Type, 크기 |
| `sync_pages` | window/page와 요청·원문 연결 |
| `source_records` | 검증 완료 후 게시 가능한 원천 record |
| `source_snapshots` | operation 단위 불변 source 세대 |
| `active_source_snapshots` | operation별 현재 source pointer |

## 우선조달 상품 설명

| 테이블 | 내용 |
|---|---|
| `priority_products` | 본품의 `product_id`, 정규 `detail_url`, 기존 provider `raw_json`. 설명 보강은 `raw_json`을 바꾸지 않음 |
| `priority_product_description_observations` | `stored`, `missing`, `failed` 시도를 수정과 삭제 없이 누적 |
| `priority_product_description_state` | 상품별 최신 observation을 가리키는 원자적 pointer |

observation은 대상 `product_id`, `contract_item_management_number`, `page_url`,
관찰된 `endpoint_url`, 요청 fingerprint, HTTP status, error code, 관찰 시각을
고정함. bounded 응답이 있으면 `response_body_sha256`가 `raw_blobs`의 exact
response bytes를 가리키며, `stored`와 `missing`에서는 JSON bytes임. `stored`행에는
HTML entity를 푼 `decoded_html`, 정규화된 한국어 plain
text인 `detail_text`, HTML SHA-256, parser version도 들어감. `missing`은 해당
관찰 시각에 게시된 설명이 없었다는 결과이며 영구 속성이 아님.

원문 pruning은 observation이 참조하는 모든 응답을 보호함. Compact runtime DB는
설명 consumer가 따로 설계될 때까지 두 설명 테이블을 빈 상태로 만들고, 설명에서만
참조한 `raw_blobs`행도 제외함.

## 정규화와 release

| 테이블 | 내용 |
|---|---|
| `products` | 물품 ID, 품목명, 카테고리, 활성 상태 |
| `catalog_offers` | 계약 가격, 단위, 계약·제품 링크 정보 |
| `product_attributes` | 정규화된 규격명·값·단위와 원문 근거 |
| `option_role_observations` | 본품·추가선택 역할과 provenance |
| `curated_relations` | 승인 workbook에서 가져온 관계 |
| `materialization_snapshots` | 정규화 결과의 불변 세대 |
| `index_versions` | index artifact와 manifest SHA |
| `release_bundles` | materialization/index/relation/ranking 조합 |
| `comparator_cache` | anchor별 1~3위 비교 payload |
| `active_release` | 웹 앱이 읽는 단일 게시 release |

## 검색 index

`search_membership`은 materialization, 카테고리, 세부 카테고리, 정규화 품목명,
활성 여부로 후보 집합을 제한함. `search_fts`는 검색어 recall에만 쓰며 후보
membership을 넓히지 않음. TF-IDF member bytes와 manifest SHA가 index 재현성을
고정함.
