#!/bin/bash
# FortiAutoConn 간편 실행 스크립트 (가상환경 자동 감지)
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python3"
if [ ! -x "$PY" ]; then
    PY="$(command -v python3)"
fi

exec "$PY" app.py
