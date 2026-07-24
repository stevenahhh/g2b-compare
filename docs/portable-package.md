# Portable package

Windows에서 Python 3.12 이상과 `uv`를 설치한 뒤 압축을 풀고 아래 명령을 실행함.

```powershell
.\scripts\run-package.ps1
```

기본 접속 주소는 `http://127.0.0.1:8765/`이며 같은 LAN에서는 `http://컴퓨터이름:8765/`로 접속함. 포트를 바꾸려면 `-Port 8765`처럼 지정함.

패키지에는 현재 로컬 SQLite 데이터와 production SPA 빌드가 포함되어 있어 첫 실행에 API 재수집이 필요하지 않음.
