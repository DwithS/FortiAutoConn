@echo off
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo PowerShell을 찾을 수 없습니다. run_windows.bat을 우클릭해서 관리자 권한으로 실행해 주세요.
  exit /b 1
)

set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=tray"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0run_windows.bat' -ArgumentList '%ARGS%' -Verb RunAs"
