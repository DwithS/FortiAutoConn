#!/bin/bash
# FortiAutoConn 간편 실행 스크립트 (가상환경 자동 감지)
cd "$(dirname "$0")" || exit 1

if [ -x ".venv/bin/python3" ]; then
    PY_DIR=".venv/bin"
    PY_ORIG=".venv/bin/python3"
else
    PY_DIR=".bin"
    PY_ORIG="$(command -v python3)"
    mkdir -p "$PY_DIR"
fi

LAUNCHER="$PY_DIR/forti-auto"
REAL="$(readlink -f "$PY_ORIG" 2>/dev/null)"
if [ -z "$REAL" ]; then
    REAL="$("$PY_ORIG" -c "import os,sys; print(os.path.realpath(sys.executable))")"
fi

# 💡 macOS Touch ID 팝업에 'python3.12'가 아닌 'forti-auto'로 표시되도록,
# 실제 인터프리터를 '독립된 복사본'으로 떠서 우리만의 코드서명 identifier를 부여합니다.
# (macOS는 프로세스 이름이 아니라 코드서명 identifier로 요청 앱을 판별하므로 단순
#  심볼릭 링크로는 표시 이름이 바뀌지 않습니다. 반드시 실제 파일 복사본이어야 하며,
#  절대 원본 공용 인터프리터 파일에 직접 서명해서는 안 됩니다 — 다른 프로젝트/venv가
#  같은 파일을 공유해서 쓸 수 있기 때문입니다.)
if [ ! -x "$LAUNCHER" ] || [ "$REAL" -nt "$LAUNCHER" ]; then
    rm -f "$LAUNCHER"   # 예전 버전이 심볼릭 링크였을 수 있으므로 반드시 먼저 제거
    cp -f "$REAL" "$LAUNCHER"
    codesign --force --sign - --identifier "com.dailyfunding.forti-auto" "$LAUNCHER" 2>/dev/null

    # 인터프리터가 @executable_path/../lib 상대경로로 공유 라이브러리를 찾는 빌드
    # (uv/python-build-standalone 등)라면 같은 상대 위치에 dylib을 연결해 줍니다.
    REAL_LIB_DIR="$(dirname "$(dirname "$REAL")")/lib"
    LAUNCHER_LIB_DIR="$(dirname "$(dirname "$LAUNCHER")")/lib"
    if [ -d "$REAL_LIB_DIR" ]; then
        mkdir -p "$LAUNCHER_LIB_DIR"
        for dylib in "$REAL_LIB_DIR"/libpython*.dylib; do
            [ -e "$dylib" ] || continue
            ln -sf "$dylib" "$LAUNCHER_LIB_DIR/$(basename "$dylib")"
        done
    fi
fi

# 위 과정이 실패했거나 실행 불가능한 환경이면 이름 커스터마이징 없이 원본으로 안전하게 폴백
if [ ! -x "$LAUNCHER" ] || ! "$LAUNCHER" -c "" 2>/dev/null; then
    echo "[run.sh] 'forti-auto' 실행 환경 구성 실패, 기본 인터프리터로 실행합니다." >&2
    LAUNCHER="$REAL"
fi

exec "$LAUNCHER" app.py
