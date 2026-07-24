# Data dictionary

## 런타임 파일

| 경로 | 내용 |
|---|---|
| `.g2b/g2b.sqlite3` | sync, snapshot, release, cache 메타데이터 |
| `.g2b/raw/` | SHA-256로 주소화된 gzip 원문 응답 |
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
