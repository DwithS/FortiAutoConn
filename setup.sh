#!/bin/bash

# ANSI Color 정의 (출력 가독성용)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}        FortiAutoConn 환경 구축 & 권한 도우미          ${NC}"
echo -e "${BLUE}====================================================${NC}"

# 1. Homebrew 및 openfortivpn 설치 검사
echo -e "\n${YELLOW}[1/3] openfortivpn 터널 바이너리 검색 중...${NC}"
if ! command -v openfortivpn &> /dev/null; then
    echo -e "시스템에 openfortivpn이 설치되어 있지 않습니다."
    if command -v brew &> /dev/null; then
        echo -e "${GREEN}Homebrew를 감지하여 openfortivpn을 자동 설치합니다...${NC}"
        brew install openfortivpn
    else
        echo -e "${RED}Homebrew가 설치되어 있지 않습니다. 수동 설치를 완료하고 다시 실행해 주세요.${NC}"
        echo -e "설치 참조: https://github.com/adrienverge/openfortivpn"
        exit 1
    fi
else
    echo -e "${GREEN}openfortivpn이 정상 감지되었습니다: $(which openfortivpn)${NC}"
fi

# 2. Python 라이브러리 의존성 설치
echo -e "\n${YELLOW}[2/3] Python 환경에 필요한 필수 패키지 설치...${NC}"

# 시스템 pip3를 직접 쓰지 않고 가상환경(.venv) 격리 방식을 유도하여 macOS 보안 차단(PEP 668) 원천 회피
if command -v uv &> /dev/null; then
    echo -e "${GREEN}시스템에서 'uv'를 감지했습니다. uv를 활용해 격리된 가상환경에 초고속 설치를 진행합니다...${NC}"
    uv venv &> /dev/null
    uv pip install -r requirements.txt
    INSTALL_OK=$?
else
    echo -e "기본 python3 venv 가상환경 빌드를 통한 의존성 격리 설치를 시도합니다..."
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Python3 도구를 찾을 수 없습니다. 맥북의 Python 환경을 점검해 주세요.${NC}"
        exit 1
    fi
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    INSTALL_OK=$?
fi

if [ $INSTALL_OK -eq 0 ]; then
    echo -e "${GREEN}Python 의존성 라이브러리가 가상환경(.venv) 내에 안전하고 투명하게 격리 구축되었습니다.${NC}"
else
    echo -e "${RED}Python 의존성 패키지 설치 도중 문제가 발생했습니다. 에러 로그를 점검해 주세요.${NC}"
    exit 1
fi

# 3. openfortivpn sudo NOPASSWD 권한 설정 등록
echo -e "\n${YELLOW}[3/3] 백그라운드 구동을 위한 openfortivpn 무암호 관리자 권한 등록...${NC}"
OPENFORTIVPN_PATH=$(which openfortivpn)

if [ -z "$OPENFORTIVPN_PATH" ]; then
    echo -e "${RED}openfortivpn의 설치 주소를 파악할 수 없습니다. 설치 단계를 먼저 통과해 주십시오.${NC}"
    exit 1
fi

# sudoers 권한 규격 정의 (admin 그룹의 사용자가 비밀번호 없이 해당 경로 바이너리 실행 허용)
SUDOERS_LINE="%admin ALL=(ALL) NOPASSWD: $OPENFORTIVPN_PATH"
SUDOERS_FILE="/etc/sudoers.d/openfortivpn"

echo -e "메뉴바 백그라운드 앱이 8시간 만료 및 최초 연결 시 무중단 연동을 위해 openfortivpn을 관리자 권한으로 호출할 수 있게 설정합니다."
echo -e "${YELLOW}안전한 설정을 위해 최초 1회, 현재 사용 중인 맥북의 OS 관리자 암호 입력을 요구합니다:${NC}"

# /etc/sudoers.d 경로 체크 및 생성
sudo mkdir -p /etc/sudoers.d
if [ $? -ne 0 ]; then
    echo -e "${RED}로컬 권한(sudo) 획득에 실패하였거나 시스템 폴더를 준비하지 못했습니다.${NC}"
    exit 1
fi

# sudoers 파일 등록
echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
# 권한 마스킹 (macOS 및 Unix 표준은 sudoers 파일을 0440 읽기 전용으로 제안하지 않으면 문법 검증에서 차단됨)
sudo chmod 0440 "$SUDOERS_FILE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}openfortivpn의 NOPASSWD 권한 부여 작업이 정상적으로 등록되었습니다!${NC}"
else
    echo -e "${RED}sudoers 파일 권한 보안 수정 중 실패했습니다.${NC}"
    exit 1
fi

echo -e "\n${BLUE}====================================================${NC}"
echo -e "${GREEN}     FortiAutoConn의 모든 구동 설정이 완료되었습니다!   ${NC}"
echo -e "${BLUE}====================================================${NC}"
echo -e "이제 메뉴바 앱을 다음 명령어로 바로 켜실 수 있습니다:\n"
echo -e "  ${YELLOW}python3 app.py${NC}\n"
