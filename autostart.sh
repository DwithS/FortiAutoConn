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
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

install_agent() {
    if [ -z "$PYTHON_BIN" ]; then
        echo -e "${RED}python3를 찾을 수 없습니다. 먼저 ./setup.sh 를 실행해 주세요.${NC}"
        exit 1
    fi

    mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

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
        <string>$PROJECT_DIR/app.py</string>
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
