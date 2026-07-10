# FortiAutoConn (FortiClient SSL-VPN 자동화 메뉴바 앱)

맥북에서 FortiClient VPN을 사용할 때 매번 **[연결 시도 ➔ 인증메일 확인 ➔ 6자리 OTP 입력]** 하던 번거로운 과정을 한 방에 자동화해 주는 macOS 메뉴바 상주 애플리케이션입니다.

`openfortivpn` 코어를 기반으로 하며, macOS의 **Touch ID(지문 인증)** 및 **시스템 Keychain(키체인)**에 연동되어 중요 자격 증명을 매우 안전하게 보호하고, **다음/카카오 IMAP 메일 감시**를 통해 인증 메일이 발송되는 즉시 OTP 코드를 스스로 검출하여 연결해 줍니다. 8시간 세션 만료 등으로 연결이 분리될 시, 백그라운드에서 지문 입력 없이 무중단으로 자동 재접속을 완료합니다.

---

## 🚀 주요 기능

1.  **네이티브 상태바 아이콘**: 메뉴바 우측 상단 상주하며 연결 상태에 따라 아이콘 색상 변경 (🔴 연결 끊김, 🟡 연결 처리 중/OTP 탐색 중, 🟢 안전 연결 성공).
2.  **지문인식(Touch ID) 및 Keychain 연동**: 최초 연결 시 Touch ID를 통해 본인 인증을 해야만 안전하게 Keychain 풀에서 접속 암호를 읽어 실행하므로 자격 증명이 절대 노출되지 않습니다.
3.  **다음/카카오 메일 OTP 자동 감지**: 1차 비밀번호 검증이 끝나 메일이 오면, 실시간으로 이메일을 분석하여 `it@daily-funding.com`이 발송한 `AuthCode` 6자리를 자동 파싱 및 기입합니다.
4.  **스마트 자동 재연결**: 8시간 세션 만료 등으로 연결이 해제되었을 때, 지문 인식을 매번 띄우지 않고 10초 대기 후 메모리 세션을 통해 알아서 백그라운드 재연결을 완료하여 업무 중단을 방지합니다.

---

## 🛠 사전 준비 사항

### 1. 다음 / 카카오 메일 IMAP 활성화
메일을 프로그램에서 조회하기 위해 반드시 본인 이메일 설정에서 IMAP 서비스가 활성화되어 있어야 합니다.

*   **다음 메일 설정 방법**:
    1. [Daum 메일](https://mail.daum.net) 로그인 ➔ 좌측 하단의 **'환경설정'** 클릭.
    2. 상단 메뉴의 **'IMAP/POP3'** 탭 선택.
    3. **'IMAP/SMTP 서비스'** 설정을 **'사용함'**으로 설정 후 저장.
*   **주의 (카카오 / 다음 2단계 인증 사용자)**:
    *   2단계 인증을 사용 중인 경우, 본인의 일반 비밀번호 대신 카카오 계정 관리 페이지에서 **[보안 ➔ 2단계 인증 ➔ 앱 비밀번호]**를 생성하여 해당 앱 비밀번호를 이메일 암호 설정에 입력해야만 로그인이 가능합니다.

---

## 📥 설치 및 설정 방법

### 1. 원클릭 설치 스크립트 실행
터미널을 열고 본 저장소 디렉토리 내에서 아래 명령을 실행합니다. 이 스크립트는 `openfortivpn` 터널 엔진(Homebrew가 없는 경우 Brew 자동 설치 포함)과 Python 모듈을 일괄 설치하고 무암호 sudoers 실행 권한을 구성합니다.

```bash
# 스크립트 실행 권한 부여
chmod +x setup.sh

# 환경 설정 도우미 구동
./setup.sh
```
*※ `setup.sh` 중간에 openfortivpn의 패스워드 무암호 실행 권한 부여를 위해 맥북의 OS 비밀번호 입력을 최초 1회 요구합니다.*

### 2. 메뉴바 애플리케이션 시작
설치가 무사히 끝나면 아래 명령어로 메뉴바 앱을 실행합니다. (가상환경 `.venv`를 자동으로 감지해 사용합니다.)

```bash
./run.sh
```
실행하면 우측 상단 메뉴바에 🔴 아이콘이 생깁니다.

### 2-1. (권장) 맥북 로그인 시 자동실행 등록
매번 터미널로 실행할 필요 없이, 맥북에 로그인하면 메뉴바 앱이 자동으로 켜지도록 macOS LaunchAgent에 등록할 수 있습니다.

```bash
# 자동실행 등록 (등록 즉시 1회 기동됨)
./autostart.sh install

# 자동실행 해제
./autostart.sh uninstall

# 등록/실행 상태 확인
./autostart.sh status
```
*※ 앱이 비정상 종료(크래시)되면 launchd가 자동으로 다시 띄워 주며, 메뉴바에서 `Quit`으로 정상 종료한 경우에는 다시 실행하지 않습니다.*

### 3. 최초 1회 설정 등록
메뉴바의 🔴 아이콘을 클릭하고 **`Settings`**를 선택하여 자격증명을 순서대로 등록합니다.
*   **VPN Host**: 사내 VPN 서버 도메인 또는 IP (예: `vpn.daily-funding.com`)
*   **VPN Port**: VPN 포트 번호 (일반적으로 `443` 또는 지정된 포트)
*   **VPN Username**: 본인의 VPN 아이디 (예: `honggildong`)
*   **VPN Password**: 본인의 VPN 로그인 패스워드
*   **IMAP Host**: 다음 메일은 `imap.daum.net`, 카카오 메일은 `imap.kakao.com`
*   **IMAP Port**: SSL 기본 포트인 `993`
*   **Mail ID**: 본인의 다음/카카오 이메일 전체 주소 (예: `user@daum.net`)
*   **Mail Password**: 메일 로그인 비밀번호 (2단계 인증자는 생성한 **앱 비밀번호**)

*※ 모든 비밀번호 정보는 소스코드 내부나 파일에 평문으로 남지 않고, macOS 기본 탑재 보안 요소인 **Keychain Access**에 암호화 저장되어 극도로 안전하게 통제됩니다.*

---

## 💻 사용 가이드

### VPN 연결 및 가동
1.  메뉴바의 🔴 아이콘 클릭 ➔ **`Connect VPN`** 선택.
2.  맥북의 **Touch ID(지문인식)** 창이 나타납니다. 지문을 가볍게 대거나 암호를 넣어 인증해 주세요.
3.  인증 성공 즉시 백그라운드 터널 구동이 시작되며 상태 아이콘이 🟡로 변경됩니다.
4.  자동으로 인증 메일 도착을 감지하여 OTP를 주입하고 완료되면 🟢로 변경되며 맥 알림이 뜹니다.

### VPN 연결 해제 (수동)
*   🟢 아이콘 클릭 ➔ **`Disconnect VPN`** 선택 시 즉시 터널이 철거되며 🔴 상태로 돌아갑니다.

---

## 🪟 Windows 포팅 프로토타입

현재 Windows 경로는 **B안 MVP**입니다. FortiClient Standalone 7.4.7 및 FortiClient 8.0.0 문서에는 `FortiVPN.exe --cli --connect --tunnel <tunnelname> [--username <username>] [--password <password>] [--savecredentials] [--keeprunning]`가 제공된다고 되어 있습니다. 단, 이 기능은 FortiClient GUI/EMS에 이미 구성된 터널만 연결할 수 있고 새 터널 생성은 지원하지 않으며, 문서상 OTP 코드 입력 인자는 없습니다. 현재 확인한 로컬 설치본은 FortiClient VPN 7.4.3.1790이고 `FortiVPN.exe --cli` 실행 시 `Option 'cli' does not exist`가 반환되어 A안 자동 연결을 사용할 수 없습니다.

Windows MVP는 다음 흐름을 제공합니다.

1. FortiClient VPN UI 실행
2. Windows UI Automation(`pywinauto`)으로 FortiClient의 `연결`/`Connect` 버튼 클릭 시도
3. FortiAutoConn이 IMAP OTP 메일을 감시
4. OTP 발견 시 Windows 클립보드에 복사
5. `안전 자동 붙여넣기`가 켜져 있고 FortiClient 창이 활성 상태이면 Ctrl+V 자동 전송, 아니면 사용자가 FortiClient OTP 입력 칸에 붙여넣기

연결 버튼이 UI Automation에 노출되지 않는 FortiClient 버전/배포판에서는 자동 클릭만 건너뛰고 기존 B안처럼 FortiClient 창을 띄운 뒤 사용자가 연결 버튼을 누르면 OTP 감시/붙여넣기는 계속 동작합니다. Settings의 `Connect Button Labels`에서 버튼명이 다른 사내 배포판의 라벨을 쉼표로 추가할 수 있습니다. Windows 실행 경로는 `C:\Program Files\Fortinet\FortiClient\FortiClient.exe` 하나만 사용합니다.

실행/패키징:

```bat
dist\FortiAutoConn.exe          :: Windows tray 상주 앱 실행 (기본, UAC 요청 없음)
dist\FortiAutoConn.exe settings :: 설정 페이지 열기 (UAC 요청 없음)
dist\FortiAutoConn.exe status   :: FortiClient 경로와 CLI 가능성 점검 (UAC 요청 없음)

:: exe 재빌드
.venv\Scripts\python.exe -m PyInstaller FortiAutoConn.spec
```

Tray 메뉴:

*   **Connect**: FortiClient를 열고 연결 버튼 자동 클릭을 시도한 뒤 OTP 감시/붙여넣기를 진행합니다.
*   **Settings**: 로컬 설정 페이지를 엽니다.
*   **Status**: FortiClient 감지 여부, 메일 설정 여부, 자동 OTP 감시/붙여넣기 상태를 표시합니다.
*   **Run at Windows startup**: Windows 로그인 시 tray 자동실행을 켜거나 끕니다.
*   **Quit**: tray 앱을 종료합니다.

Tray 실행 시 OTP 메일 감시와 안전 자동 붙여넣기는 기본값 `true`로 동작합니다. FortiClient/FortiVPN 창이 없으면 메일 감시는 휴면 상태로 대기하고, 창이 감지되면 활성화됩니다. OTP 복사 후 토큰 칸의 기존 값을 Ctrl+A로 선택하고 Delete로 비운 뒤 Ctrl+V와 Enter를 보냅니다. Windows 자동실행은 Startup 폴더에 숨김 실행용 `FortiAutoConn.vbs` 런처를 등록하므로 로그인 시 cmd 창을 띄우지 않습니다.

Windows 설정은 `%APPDATA%\FortiAutoConn\config.json`에 저장되고, 메일 비밀번호는 `keyring`을 통해 Windows Credential Manager에 저장됩니다. FortiClient CLI 자동 연결이 가능한 사내 배포판/버전이 확인되면 `windows_app.py`의 `probe_forticlient_cli()` 결과를 기준으로 A안 백엔드를 추가할 수 있습니다.

### 자동 재연결 세부 사항
*   사용자가 `Disconnect VPN`을 명시적으로 누른 것이 아님에도 외부 요인(8시간 세션 무효화, Wi-Fi 신호 유실 등)으로 인해 접속이 차단되면, 시스템이 이를 즉시 파악하고 10초 후에 조용히 백그라운드 재접속 작업을 돌립니다.
*   이때는 최초 연결 당시 확보한 활성 세션(캐시)을 쓰기 때문에 Touch ID를 추가로 인식시킬 필요가 전혀 없어 매우 자연스러운 무중단 업무 지속이 보장됩니다.
