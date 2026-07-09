#!/bin/bash
# FortiAutoConn 로그인 자동실행(LaunchAgent) 등록/해제 도우미
#
# 사용법:
#   ./autostart.sh install    # 로그인 시 자동실행 등록 (즉시 1회 기동 포함)
#   ./autostart.sh uninstall  # 자동실행 해제 및 실행 중인 앱 종료
#   ./autostart.sh status     # 현재 등록/실행 상태 확인

set -u

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

LABEL="com.dailyfunding.fortiautoconn"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
GUI_DOMAIN="gui/$(id -u)"

# 가상환경 파이썬 우선 사용 (setup.sh가 만든 .venv), 없으면 시스템 python3
if [ -x "$PROJECT_DIR/.venv/bin/python3" ]; then
    PY_DIR="$PROJECT_DIR/.venv/bin"
    PY_ORIG="$PROJECT_DIR/.venv/bin/python3"
else
    PY_DIR="$PROJECT_DIR/.bin"
    PY_ORIG="$(command -v python3)"
fi
# 💡 macOS Touch ID / 암호 인증 팝업에 'python3.12' 대신 'forti-auto'로 표시되도록
# 실제 인터프리터를 '독립된 복사본'으로 떠서 우리만의 코드서명 identifier를 부여합니다.
PYTHON_BIN="$PY_DIR/forti-auto"

install_agent() {
    if [ -z "$PY_ORIG" ]; then
        echo -e "${RED}python3를 찾을 수 없습니다. 먼저 ./setup.sh 를 실행해 주세요.${NC}"
        exit 1
    fi

    mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs" "$PY_DIR"

    REAL="$(readlink -f "$PY_ORIG" 2>/dev/null)"
    if [ -z "$REAL" ]; then
        REAL="$("$PY_ORIG" -c "import os,sys; print(os.path.realpath(sys.executable))")"
    fi

    # macOS는 프로세스 이름이 아니라 코드서명 identifier로 요청 앱을 판별하므로,
    # 단순 심볼릭 링크로는 표시 이름이 바뀌지 않습니다. 반드시 '실제 파일 복사본'이어야 하며,
    # 절대 원본 공용 인터프리터 파일에 직접 서명해서는 안 됩니다 (다른 프로젝트/venv가 공유할 수 있음).
    if [ ! -x "$PYTHON_BIN" ] || [ "$REAL" -nt "$PYTHON_BIN" ]; then
        rm -f "$PYTHON_BIN"   # 예전 버전이 심볼릭 링크였을 수 있으므로 반드시 먼저 제거
        cp -f "$REAL" "$PYTHON_BIN"
        codesign --force --sign - --identifier "com.dailyfunding.forti-auto" "$PYTHON_BIN" 2>/dev/null

        REAL_LIB_DIR="$(dirname "$(dirname "$REAL")")/lib"
        LAUNCHER_LIB_DIR="$(dirname "$PY_DIR")/lib"
        if [ -d "$REAL_LIB_DIR" ]; then
            mkdir -p "$LAUNCHER_LIB_DIR"
            for dylib in "$REAL_LIB_DIR"/libpython*.dylib; do
                [ -e "$dylib" ] || continue
                ln -sf "$dylib" "$LAUNCHER_LIB_DIR/$(basename "$dylib")"
            done
        fi
    fi

    # 구성이 실패했거나 실행 불가능한 환경이면 이름 커스터마이징 없이 원본으로 안전하게 폴백
    if [ ! -x "$PYTHON_BIN" ] || ! "$PYTHON_BIN" -c "" 2>/dev/null; then
        echo -e "${YELLOW}'forti-auto' 실행 환경 구성 실패, 기본 인터프리터로 등록합니다.${NC}"
        PYTHON_BIN="$REAL"
    fi

    # launchd는 PATH를 거의 비워둔 채 앱을 띄우므로, Homebrew 경로(openfortivpn 위치)를
    # 명시적으로 넣어주지 않으면 자동실행으로 뜬 앱이 openfortivpn을 찾지 못합니다.
    cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$PROJECT_DIR/src/app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <!-- 비정상 종료(크래시) 시에만 자동 재기동. 메뉴바에서 Quit으로 정상 종료하면 다시 띄우지 않음 -->
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/launchd.err.log</string>
</dict>
</plist>
EOF

    # 기존 등록이 있으면 정리 후 재등록
    launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null
    if launchctl bootstrap "$GUI_DOMAIN" "$PLIST_PATH"; then
        launchctl enable "$GUI_DOMAIN/$LABEL" 2>/dev/null
        echo -e "${GREEN}✅ 자동실행 등록 완료!${NC}"
        echo -e "   - 지금 즉시 메뉴바에 앱이 기동되었고, 앞으로 맥북 로그인 시 자동으로 실행됩니다."
        echo -e "   - 사용 파이썬: $PYTHON_BIN"
        echo -e "   - 해제하려면: ${YELLOW}./autostart.sh uninstall${NC}"
    else
        echo -e "${RED}❌ launchctl 등록에 실패했습니다. 이미 실행 중인 앱이 있다면 종료 후 다시 시도해 주세요.${NC}"
        exit 1
    fi
}

uninstall_agent() {
    launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null
    if [ -f "$PLIST_PATH" ]; then
        rm -f "$PLIST_PATH"
        echo -e "${GREEN}✅ 자동실행이 해제되었고 실행 중인 앱도 종료했습니다.${NC}"
    else
        echo -e "${YELLOW}등록된 자동실행 설정이 없습니다.${NC}"
    fi
}

status_agent() {
    if [ -f "$PLIST_PATH" ]; then
        echo -e "${GREEN}● 자동실행 등록됨:${NC} $PLIST_PATH"
    else
        echo -e "${YELLOW}○ 자동실행 미등록${NC}"
    fi
    if launchctl print "$GUI_DOMAIN/$LABEL" &>/dev/null; then
        echo -e "${GREEN}● launchd에 로드되어 실행 관리 중입니다.${NC}"
    else
        echo -e "${YELLOW}○ 현재 launchd에 로드되어 있지 않습니다.${NC}"
    fi
}

case "${1:-}" in
    install)   install_agent ;;
    uninstall) uninstall_agent ;;
    status)    status_agent ;;
    *)
        echo "사용법: $0 {install|uninstall|status}"
        exit 1
        ;;
esac
