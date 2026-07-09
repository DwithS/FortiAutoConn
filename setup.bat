@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ====================================================
echo      FortiAutoConn Windows 환경 설정 도우미
echo ====================================================
echo.

:: 1. 파이썬 설치 여부 점검
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [오류] 시스템에서 python을 찾을 수 없습니다.
    echo 파이썬(Python 3.8 이상)을 먼저 설치하시고,
    echo 설치 시 'Add Python to PATH' 옵션을 체크해 주세요.
    pause
    exit /b 1
)

:: 2. 가상환경 생성 (.venv)
if not exist ".venv" (
    echo [+] 가상환경(.venv)을 생성 중입니다...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [오류] 가상환경 생성에 실패했습니다.
        pause
        exit /b 1
    )
) else (
    echo [*] 이미 가상환경(.venv)이 존재합니다.
)

:: 3. 가상환경 활성화 및 필수 라이브러리 설치
echo [+] 윈도우 지원 라이브러리를 설치하는 중입니다...
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip

:: keyring, pystray, pillow, winsdk 개별 설치 (macOS 전용 종속성인 pyobjc 및 pexpect 제외)
pip install keyring pystray pillow winsdk

if %errorlevel% neq 0 (
    echo [오류] 일부 라이브러리 설치에 실패했습니다. 네트워크 상태를 확인해 주세요.
    pause
    exit /b 1
)

echo.
echo ====================================================
echo 🛡️ openfortivpn.exe 다운로드 안내 🛡️
echo ====================================================
echo Windows 환경에서 VPN 연결을 구동하기 위해서는 openfortivpn.exe가 필요합니다.
echo 아래 링크에서 Windows 버전 openfortivpn 빌드를 다운로드해 주세요:
echo.
echo - 다운로드 링크: https://github.com/adrienverge/openfortivpn/releases
echo   (또는 윈도우용으로 빌드된 openfortivpn.exe 바이너리 확보)
echo.
echo 다운로드받은 'openfortivpn.exe' 파일을 이 프로젝트 폴더인:
echo '%CD%' 안에 배치하거나,
echo 시스템 환경 변수(PATH)에 등록된 폴더에 배치해 주세요.
echo ====================================================
echo.

echo [+] 가상환경 구성 및 윈도우 종속성 설치가 완료되었습니다.
echo.
echo [안내] 이제 'run.bat'을 실행하면 윈도우용 트레이 앱이 켜집니다.
echo 로그인 시 자동 시작 등록을 원하시면 가상환경이 켜진 터미널에서:
echo   python autostart_windows.py install
echo 을 입력해 실행해 주세요.
echo.

pause
exit /b 0
