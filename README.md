# 나라장터 유사 물품 검색

나라장터 종합쇼핑몰 OpenAPI 데이터를 로컬 SQLite에 수집하고, 같은 품목·
카테고리 안에서 규격과 가격이 비슷한 물품 3개를 비교하는 데스크톱용 웹 앱임.
검색 중에는 외부 API를 호출하지 않음.

## 요구 환경

- Windows
- Python 3.12 또는 3.13
- `uv`
- 공공데이터포털 인증키

## 실행

프로젝트 루트 `.env`에 다음 한 줄을 넣고 터미널에서 Python 런처를 실행함.

```dotenv
G2B_SERVICE_KEY=<발급받은_인증키>
```

```powershell
uv run python .\scripts\start.py --home .g2b
```

런처는 프로젝트 루트 `.env`를 읽음. 현재 프로세스에 비어 있지 않은
`G2B_SERVICE_KEY`가 있으면 그 값을 우선 사용함. `.env`는 Git에 추가하지 않음.

별도 관계 XLSX는 검색에 필요하지 않음. 설정하지 않으면 빈 관계 스냅샷으로
실행되며 카테고리·규격·가격 유사도만 사용함.

데이터 준비만 하고 서버를 열지 않으려면 다음과 같이 실행함.

```powershell
uv run python .\scripts\start.py --home .g2b --provision-only
```

우선수집 엑셀의 업체·옵션을 SQLite에 넣고 API와 상세페이지 수집을 이어서 실행하려면 다음 한 명령을 사용함. API는 실행마다 지정한 호출 수 안에서 진행하고, 실패하거나 중단된 대상은 다음 실행 때 이어서 처리함.

```powershell
.\scripts\priority.ps1 -Action sync -MaxCalls 10000
```

현재 적재 상태만 확인하려면 다음과 같이 실행함.

```powershell
.\scripts\priority.ps1 -Action status
```

브라우저를 열지 않고 서버만 시작하려면 다음과 같이 실행함.

```powershell
uv run python .\scripts\start.py --home .g2b --no-browser
```

### 다른 머신에서 내부망 공개

런처는 머신별 IP를 코드에 넣지 않고 `0.0.0.0:8765`에 bind하므로, 저장소와
사용할 HOME 디렉터리를 준비한 다른 Windows 머신에서도 같은 명령으로 실행할
수 있음.

```powershell
uv sync --frozen
uv run python .\scripts\start.py --home D:\g2b-data --no-browser
```

실행 머신에서는 `http://127.0.0.1:8765/`로 확인하고, 같은 AP·내부망의 다른
머신에서는 `http://<실행_머신의_IPv4>:8765/`로 접속함. 실행 머신의 IPv4는
`ipconfig`로 확인함. Windows 방화벽 알림이 표시되면 사설·도메인 네트워크만
허용하고, 공유기 포트 포워딩은 설정하지 않음. `Ctrl+C`로 런처를 종료하면
자식 서버도 함께 종료됨.

이미 준비된 HOME을 별도 provisioning 없이 바로 제공할 때는 다음 명령도
동일하게 전체 인터페이스에 bind함.

```powershell
uv run g2b-compare --home D:\g2b-data serve --host 0.0.0.0 --port 8765
```

새 HOME에는 저장소의 검증된 `docs/api-contract-observed.json`이 자동 복사됨.
최초 전체 동기화는 API 호출 한도 때문에 여러 날 걸릴 수 있음. 안전 한도에서
중단되면 저장된 페이지 다음부터 재개되므로 24시간 rolling window가 지난 뒤
같은 명령을 다시 실행하면 됨.

준비가 끝나면 이 머신에서 여는 기본 주소는 `http://127.0.0.1:8765/`이며,
서버 자체는 내부망 공유를 위해 모든 IPv4 인터페이스에 bind함.

## 주요 명령

`uv run g2b-compare --home .g2b sync ...` 직접 실행은 고급 운영용임. 이 `sync`
명령은 `.env`를 읽지 않으므로 인증키가 필요하면 호출 프로세스에
`G2B_SERVICE_KEY`를 별도로 설정함.

```powershell
uv run g2b-compare --home .g2b verify
uv run g2b-compare --home .g2b sync full
uv run g2b-compare --home .g2b sync delta
uv run g2b-compare --home .g2b sync attributes --max-batches 100
uv run g2b-compare --home .g2b verify-secrets --all-storage
uv run g2b-compare --home .g2b serve --host 127.0.0.1 --port 8765
```

운영 절차는 [동기화 runbook](docs/sync-runbook.md), 현재 제한은
[limitations](docs/limitations.md)에 정리되어 있음.

## 검증

```powershell
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest -q
```

`.g2b/`, `.env`, 인증키, 원문 API payload는 Git에 추가하지 않음.
