@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where uv >nul 2>nul
  if %ERRORLEVEL%==0 (
    uv venv || exit /b 1
    uv pip install -r requirements.txt || exit /b 1
  ) else (
    py -3 -m venv .venv || exit /b 1
    .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
  )
  set "PY=.venv\Scripts\python.exe"
)

"%PY%" app.py %*
