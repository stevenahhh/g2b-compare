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
