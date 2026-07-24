@echo off
chcp 65001 >nul
setlocal

title G2B Compare - Local logout
echo.
echo Git 및 Tailscale 로그아웃 시작함.
echo.

set "GIT_CMD="
where git >nul 2>&1
if not errorlevel 1 set "GIT_CMD=git"
if not defined GIT_CMD if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT_CMD=%ProgramFiles%\Git\cmd\git.exe"

if not defined GIT_CMD (
    echo [건너뜀] Git을 찾지 못했음.
) else (
    echo [Git] GitHub HTTPS 인증정보 삭제 중...
    (
        echo protocol=https
        echo host=github.com
        echo.
    ) | "%GIT_CMD%" credential reject >nul 2>&1
    if errorlevel 1 (
        echo [실패] GitHub HTTPS 인증정보를 삭제하지 못했음.
    ) else (
        echo [완료] GitHub HTTPS 인증정보 삭제함.
    )
    where gh >nul 2>&1
    if not errorlevel 1 (
        gh auth logout --hostname github.com --yes >nul 2>&1
        if errorlevel 1 (
            echo [안내] GitHub CLI 로그인 정보가 없거나 삭제하지 못했음.
        ) else (
            echo [완료] GitHub CLI 로그인 정보 삭제함.
        )
    )
)

set "TAILSCALE_CMD="
where tailscale >nul 2>&1
if not errorlevel 1 set "TAILSCALE_CMD=tailscale"
if not defined TAILSCALE_CMD if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TAILSCALE_CMD=%ProgramFiles%\Tailscale\tailscale.exe"
if not defined TAILSCALE_CMD if exist "%ProgramFiles(x86)%\Tailscale\tailscale.exe" set "TAILSCALE_CMD=%ProgramFiles(x86)%\Tailscale\tailscale.exe"

if not defined TAILSCALE_CMD (
    echo [건너뜀] Tailscale을 찾지 못했음.
) else (
    echo [Tailscale] 세션 로그아웃 중...
    "%TAILSCALE_CMD%" logout
    if errorlevel 1 (
        echo [실패] Tailscale 로그아웃 실패함. 관리자 권한으로 다시 실행해 보셈.
    ) else (
        echo [완료] Tailscale 로그아웃함.
    )
)

echo.
echo 로그아웃 작업 끝남.
pause
endlocal
