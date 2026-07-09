@echo off
chcp 65001 >nul

:: 1. 관리자 권한 여부 점검
net session >nul 2>&1
if %errorLevel% == 0 (
    goto :run_app
) else (
    echo [+] 관리자 권한이 필요합니다. UAC 권한 상승을 요청합니다...
    :: PowerShell을 이용해 자기 자신(%0)을 관리자 권한(RunAs)으로 재실행
    powershell -NoProfile -Command "Start-Process -FilePath '%0' -Verb RunAs"
    exit /b
)

:run_app
:: 2. UAC 실행 시 작업 디렉토리가 System32로 변경되므로 배치 파일 폴더로 명시적 이동
cd /d "%~dp0"

echo ====================================================
echo      FortiAutoConn Windows 트레이 애플리케이션
echo ====================================================
echo.
echo [*] 가상환경 활성화 중...
if not exist ".venv" (
    echo [오류] 가상환경(.venv)이 존재하지 않습니다. 먼저 setup.bat을 실행해 주세요.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

:: openfortivpn.exe 검사 (프로젝트 루트 또는 PATH 상에 있는지 확인)
where openfortivpn.exe >nul 2>nul
if %errorlevel% neq 0 (
    if not exist "openfortivpn.exe" (
        echo [경고] openfortivpn.exe를 찾을 수 없습니다.
        echo VPN 연결 시작 전에 공식 openfortivpn 빌드 파일(openfortivpn.exe)을
        echo 이 프로젝트 디렉토리에 배치해 주세요:
        echo '%CD%'
        echo.
    )
)

echo [+] FortiAutoConn 트레이 앱을 백그라운드로 가동합니다.
echo [안내] 작업 표시줄 오른쪽 아래 알림 영역(트레이)에서 아이콘을 클릭하여 설정 및 VPN 연결을 수행할 수 있습니다.
echo.

python app_windows.py
exit /b 0
