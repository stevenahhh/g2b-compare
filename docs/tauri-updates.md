# Tauri 데스크톱 업데이트 배포

## 배포 구조

- 소스 저장소: 비공개 `stevenahhh/g2b-compare`
- 배포 채널: 공개 `stevenahhh/g2b-compare-releases`의 최신 정식 GitHub Release
- 설치 형식: Windows NSIS `currentUser`
- 업데이트 검증: Tauri updater 서명
- 업데이트 확인: 앱 시작 시 자동 확인, 새 버전이 있을 때 사용자 확인 후 설치
- 사용자 데이터: 설치 폴더가 아닌 `%APPDATA%\kr.co.g2bcompare.desktop`에 유지

업데이트는 실행 파일과 번들 리소스만 교체한다. 다음 사용자 파일은 업데이트 패키지에 포함하지 않으며 기존 파일이 있으면 seed로 덮어쓰지 않는다.

- `g2b.sqlite3`
- `catalog-view.sqlite3`
- `estimate-view.sqlite3`
- `desktop-view.sqlite3`
- `offline-replay.sqlite3`
- `templates/`
- `exports/`

앱 identifier `kr.co.g2bcompare.desktop`, NSIS 설치 범위 `currentUser`, 데이터 경로를 변경하면 기존 데이터가 사라진 것처럼 보일 수 있으므로 변경하지 않는다.

## 최초 GitHub 설정

비공개 소스 저장소 `g2b-compare`의 Settings → Secrets and variables → Actions에 다음 repository secret을 등록한다.

- `G2B_SERVICE_KEY`: release 빌드에 사용하는 서비스 키
- `TAURI_SIGNING_PRIVATE_KEY`: `C:\Users\steve\.tauri\g2b-compare-updater.key` 파일의 전체 내용
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: 현재 키는 비밀번호 없이 생성했으므로 빈 값으로 두거나 등록하지 않는다
- `RELEASE_REPO_TOKEN`: 공개 `g2b-compare-releases` 저장소의 Contents 읽기/쓰기 권한만 가진 fine-grained personal access token

개인키는 저장소에 복사하거나 커밋하지 않는다. `C:\Users\steve\.tauri\g2b-compare-updater.key`와 복구용 보안 백업을 모두 잃으면 기존 설치본이 수락하는 업데이트를 더 이상 만들 수 없다.

## 릴리스 절차

1. `desktop/package.json`, `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/tauri.conf.json`의 버전을 동일한 SemVer로 올린다.
2. 로컬에서 `npm run check`, `npm test`, Rust 테스트와 `npm run tauri -- build`를 통과시킨다.
3. 변경사항을 `main`에 병합한다.
4. 동일 버전 태그를 푸시한다. 예: `git tag app-v0.2.0` 후 `git push origin app-v0.2.0`.
5. 공개 `g2b-compare-releases` 저장소에서 Actions가 만든 draft release의 NSIS 설치 파일, updater archive, `.sig`, `latest.json`을 확인한다.
6. draft를 게시한다. 게시 전에는 `/releases/latest/download/latest.json`에서 검색되지 않는다.
7. 이전 버전 설치본에서 업데이트 감지, 다운로드, 재시작, 사용자 데이터 보존을 확인한다.

릴리스 태그와 `tauri.conf.json` 버전이 다르면 workflow가 빌드를 중단한다. Pull request에는 서명 키가 제공되지 않으며, `app-v*` 태그에서만 release job이 실행된다.

## 보안 및 운영 제한

- 업데이트 endpoint는 공개 배포 전용 저장소의 HTTPS GitHub URL만 사용한다. 비공개 소스 저장소의 release URL은 익명 앱에서 읽을 수 없으므로 사용하지 않는다.
- `RELEASE_REPO_TOKEN`은 앱에 포함하지 않는다. private Actions runner에서 release artifact를 업로드할 때만 사용한다.
- `latest.json`은 탐색 정보이며 실제 신뢰 기준은 앱에 내장된 공개키와 artifact 서명이다.
- Windows Authenticode 인증서는 updater 서명과 별개다. 외부 배포 전에 코드 서명 인증서를 추가해야 SmartScreen의 미확인 게시자 경고를 줄일 수 있다.
- 데이터베이스 migration은 forward-only다. 새 버전 배포 전 실제 이전 버전 데이터로 업그레이드 테스트하며, 릴리스 후 단순 downgrade를 지원한다고 가정하지 않는다.
