# Sync runbook

## 최초 준비

프로젝트 루트 `.env`에 다음 한 줄을 넣고 Python 런처로 데이터만 준비함.

```dotenv
G2B_SERVICE_KEY=<발급받은_인증키>
```

```powershell
uv run python .\scripts\start.py --home .g2b --provision-only
```

런처는 프로젝트 루트 `.env`를 읽음. 현재 프로세스에 비어 있지 않은
`G2B_SERVICE_KEY`가 있으면 그 값을 우선 사용함. `.env`는 Git에 추가하지 않음.

런처는 dependency 확인, DB migration, 검증 계약 복사, full sync, attribute sync,
빈 관계 snapshot, materialization, index, cache, verify, 비밀검사를 순서대로 실행함.

준비 뒤 서버를 시작하려면 다음과 같이 실행함.

```powershell
uv run python .\scripts\start.py --home .g2b
```

브라우저를 열지 않으려면 다음과 같이 실행함.

```powershell
uv run python .\scripts\start.py --home .g2b --no-browser
```

## 호출 한도와 재개

종합쇼핑몰 품목정보 API는 공급자 계정 화면에서 확인된 일일 한도 1,000회를
사용함. 물품목록정보서비스의 개별속성 수집은 운영 승인값인 10,000회를 로컬
호출 장부의 상한으로 사용함. UI 검색은 게시된 로컬 데이터만 읽으므로 호출
횟수 제한이 없음.
공공데이터포털의 실시간 잔여 호출량을 조회하는 API는 없으므로 별도 안전 여유는 차감하지 않음.
호출은 네트워크 전 `api_call_ledger`에 예약되며 성공 여부와 관계없이 환불하지
않음. 한도에 도달하면 `sync_runs.cursor_json`의 다음 window/page에서 재개함.
CLI는 `quota-ceiling-exhausted`와 UTC `resume_not_before`를 JSON으로 출력함.
`sync full` 실패는 검증된 안전 receipt code만 표시하며, 자식 프로세스의 임의 오류
문자열은 의도적으로 표시하지 않음.

rolling 24시간 기준 재개 가능 시각은 다음 쿼리로 확인함.

```powershell
sqlite3 .g2b/g2b.sqlite3 "
SELECT datetime(MIN(attempted_at_utc), '+24 hours')
FROM api_call_ledger
WHERE operation='getMASCntrctPrdctInfoList';"
```

해당 시각이 지난 뒤 같은 명령을 다시 실행함.

```powershell
uv run python .\scripts\start.py --home .g2b --provision-only
```

부분 실행은 source snapshot이나 release를 게시하지 않음.

## 주기 갱신

ready release가 있는 상태에서 다음 순서로 갱신함.
`uv run g2b-compare --home .g2b sync ...` 직접 실행은 고급 운영용이며 `.env`를
읽지 않음. 인증키가 필요하면 호출 프로세스에 `G2B_SERVICE_KEY`를 별도로 설정함.

```powershell
uv run g2b-compare --home .g2b sync delta
uv run g2b-compare --home .g2b sync attributes --max-batches 100
uv run g2b-compare --home .g2b import-relations
uv run g2b-compare --home .g2b materialize
uv run g2b-compare --home .g2b rebuild-index
uv run g2b-compare --home .g2b precompute
uv run g2b-compare --home .g2b verify
uv run g2b-compare --home .g2b verify-secrets --all-storage
```

각 단계가 성공한 뒤에만 다음 단계로 진행함. 실패 시 기존 active release는
그대로 유지됨.

## 우선조달 상품 설명 수집

이 작업은 일반 앱 실행과 분리된 명시적 live 수집임. 현재 본품 27,757개에는
모두 `product_id`와 `ctrtItemMngNo`가 든 정규 상세 페이지 URL이 있음. 전체
대상을 수집하려면 프로젝트 루트에서 다음 명령을 실행함.

```powershell
g2b-priority --database .g2b/g2b.sqlite3 crawl-details --concurrency 20
```

`--concurrency` 기본값은 8이고 허용 범위는 1부터 20까지임. `--detail-limit N`은
이번 실행의 대상을 product ID 순서로 양수 N개까지 제한함. `--retry-missing`은 이전
최신 결과가 `missing`인 대상도 다시 확인하고, `--force`는 결과와 관계없이 모든
대상을 다시 관찰함.

기본 재개에서는 관찰이 없거나 최신 결과가 `failed`인 대상을 자동 선택함. 현재
URL이나 `ctrtItemMngNo`가 최신 관찰의 대상과 달라진 경우도 자동으로 다시
대기열에 들어감. `missing`은 관찰 시각에 게시된 설명이 없었다는 뜻이며 영구
사실이 아님.

실행마다 ephemeral Playwright browser 한 개가 첫 상품 페이지를 거쳐 공개 SSO
cookie를 만든 뒤, 같은 context에서 아래 관찰된 WebSquare endpoint로 고정
POST를 직접 보냄.

```text
https://shop.g2b.go.kr/gm/gms/gmsf/GdsDtlInfo/selectGdsDtlInfoMngDtl.do
```

이 endpoint는 공식 OpenAPI가 아니라 종합쇼핑몰 사이트의 관찰 계약임. 인증 실패,
응답 schema 변경, HTTP 429가 나오면 현재 batch 이후 새 dispatch를
멈춤. `bootstrap_failed`, `session_invalid`, `contract_changed`, `rate_limited`를
확인한 뒤 같은 명령으로 재개함. 개별 timeout과 전송 실패도 다음 기본 실행에서
자동 재시도됨.

응답은 최대 2,000,000바이트로 제한됨. 정상 `stored`와 `missing` 응답의 exact
JSON bytes, 그리고 실패 때 수신한 bounded body는 `.g2b/raw`에
content-addressed gzip으로 저장됨. 설명 HTML이 참조하는 이미지, font, media의
파일 bytes는 내려받거나 저장하지 않음. `priority_products.raw_json`은 변경되지
않음.

### 결과 대조

현재 대상이 완전한지 먼저 확인함. 세 값은 모두 27,757이어야 함.

```powershell
sqlite3 .g2b/g2b.sqlite3 "
SELECT COUNT(*) AS total_targets,
       SUM(product_id <> '') AS with_product_id,
       SUM(
         instr(detail_url, 'ctrtItemMngNo=') > 0
         AND json_extract(raw_json, '$.ctrtItemMngNo') =
             substr(detail_url, instr(detail_url, 'ctrtItemMngNo=') +
                    length('ctrtItemMngNo='))
       ) AS with_canonical_target
FROM priority_products;"
```

상품별 최신 결과 수는 다음 쿼리로 대조함.

```powershell
sqlite3 .g2b/g2b.sqlite3 "
SELECT observation.outcome, COUNT(*)
FROM priority_product_description_state AS state
JOIN priority_product_description_observations AS observation
  ON observation.id = state.latest_observation_id
GROUP BY observation.outcome
ORDER BY observation.outcome;"
```

현재 target 기준 관찰 coverage와 기본 재개 대상은 다음 쿼리로 확인함.
`default_pending`이 0이면 현재 URL과 관리번호에 대해 실패하지 않은 최신 관찰이
모두 있음.

```powershell
sqlite3 .g2b/g2b.sqlite3 "
WITH current_targets AS (
  SELECT product_id, detail_url AS page_url,
         substr(detail_url, instr(detail_url, 'ctrtItemMngNo=') +
                length('ctrtItemMngNo=')) AS management_number
  FROM priority_products
), latest AS (
  SELECT state.product_id, observation.page_url,
         observation.contract_item_management_number AS management_number,
         observation.outcome
  FROM priority_product_description_state AS state
  JOIN priority_product_description_observations AS observation
    ON observation.id = state.latest_observation_id
)
SELECT COUNT(*) AS total_targets,
       SUM(latest.product_id IS NOT NULL) AS with_latest_observation,
       SUM(latest.page_url = current_targets.page_url AND
           latest.management_number = current_targets.management_number)
         AS current_target_covered,
       SUM(latest.product_id IS NULL OR
           latest.page_url <> current_targets.page_url OR
           latest.management_number <> current_targets.management_number OR
           latest.outcome = 'failed') AS default_pending
FROM current_targets
LEFT JOIN latest USING (product_id);"
```

Raw body integrity는 gzip을 풀어 `raw_blobs.body_sha`와 `byte_count`를 다시 계산해
확인함. 아래 명령은 설명 observation이 참조한 모든 응답을 검사하고, 손상되거나
없는 파일이 하나라도 있으면 실패함.

```powershell
@'
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

with sqlite3.connect('.g2b/g2b.sqlite3') as db:
    rows = db.execute('''
        SELECT DISTINCT observation.response_body_sha256,
                        blob.raw_path, blob.byte_count
        FROM priority_product_description_observations AS observation
        LEFT JOIN raw_blobs AS blob
          ON blob.body_sha = observation.response_body_sha256
        WHERE observation.response_body_sha256 IS NOT NULL
        ORDER BY observation.response_body_sha256
    ''').fetchall()

bad = []
for expected_sha, raw_path, expected_size in rows:
    if raw_path is None:
        bad.append([expected_sha, 'missing_raw_blob_metadata'])
        continue
    try:
        body = gzip.decompress(Path(raw_path).read_bytes())
    except Exception as error:
        bad.append([expected_sha, type(error).__name__])
        continue
    if len(body) != expected_size or hashlib.sha256(body).hexdigest() != expected_sha:
        bad.append([expected_sha, 'digest_or_size_mismatch'])

print(json.dumps({'checked': len(rows), 'bad': bad}, ensure_ascii=False))
raise SystemExit(bool(bad))
'@ | uv run python -
```

Raw pruning은 설명 observation의 응답 참조를 보호함. Compact runtime DB는 별도
consumer를 설계할 때까지 설명 observation과 그 전용 raw 참조를 제외함. 일반 앱
경로는 계속 offline-only이며, consumer를 추가할 때도 `detail_text`만 노출하고
provider `decoded_html`은 렌더링하지 않음.

## 상태 확인

```powershell
uv run g2b-compare --home .g2b verify
Invoke-RestMethod http://127.0.0.1:8765/healthz
Invoke-RestMethod http://127.0.0.1:8765/readyz
```

`readyz`가 200일 때만 검색을 운영 상태로 봄. empty, stale, partial,
corrupt-index, live-gate는 UI와 JSON 상태에 그대로 표시됨.

## 비밀과 원문

- 인증키는 `G2B_SERVICE_KEY` 환경변수로만 전달함.
- 요청 manifest와 로그에는 인증키를 넣지 않음.
- `.g2b/`, `.env`, 원문 payload를 Git에 추가하지 않음.
- 운영 전후 `verify-secrets --all-storage`를 실행함.
