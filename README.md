# FortiAutoConn (FortiClient SSL-VPN 자동화 앱 - macOS & Windows 지원)

맥북 및 윈도우 환경에서 FortiClient VPN을 사용할 때 매번 **[연결 시도 ➔ 인증메일 확인 ➔ 6자리 OTP 입력]** 하던 번거로운 과정을 한 방에 자동화해 주는 상주형 데스크톱 애플리케이션입니다.

`openfortivpn` 코어를 기반으로 하며, 각 OS의 안전한 기본 보안 저장소 및 네이티브 생체 인증에 연동되어 중요 자격 증명을 보호합니다. **다음/카카오 IMAP 메일 감시**를 통해 인증 메일이 발송되는 즉시 OTP 코드를 스스로 검출하여 연결해 줍니다. 8시간 세션 만료 등으로 연결이 분리될 시, 백그라운드에서 지문/PIN 입력 없이 무중단으로 자동 재접속을 완료합니다.

---

## 🚀 주요 기능

1. **OS 네이티브 상태바/트레이 아이콘**:
   - **macOS**: 메뉴바 우측 상단 상주하며 연결 상태에 따라 아이콘 색상 변경 (🔴 연결 끊김, 🟡 연결 처리 중, 🟢 안전 연결 성공)
   - **Windows**: 작업표시줄 알림 영역(System Tray)에 상주하며 동일하게 상태별 색상 원형 아이콘 표시 및 Windows Hello 토스트 알림 연동
2. **생체인식 및 보안 자격증명 연동**:
   - **macOS**: **Touch ID**를 통해 본인 인증을 해야만 안전하게 **시스템 Keychain** 풀에서 접속 암호를 읽어 실행
   - **Windows**: **Windows Hello(지문, 얼굴, PIN)**를 통해 본인 인증을 해야만 안전하게 **Windows 자격 증명 관리자**에서 접속 암호를 로드
3. **다음/카카오 메일 OTP 자동 감지**: 1차 비밀번호 검증이 끝나 메일이 오면, 실시간으로 이메일을 분석하여 `it@daily-funding.com`이 발송한 `AuthCode` 6자리를 자동 파싱 및 주입합니다.
4. **스마트 자동 재연결**: 8시간 세션 만료 등으로 연결이 해제되었을 때, 매번 추가 인증을 띄우지 않고 10초 대기 후 메모리 세션을 통해 알아서 백그라운드 재연결을 완료하여 업무 중단을 방지합니다.

---

## 📁 디렉토리 구조

프로젝트 코드는 다음과 같이 정리되어 있습니다:
```
zealous-kepler/
├── src/                     # Python 소스코드 디렉토리
│   ├── app.py               # macOS 메뉴바 진입점
│   ├── app_windows.py       # Windows 트레이 진입점
│   ├── keychain_manager.py  # 공통: 자격증명 및 생체 인증 관리
│   ├── mail_checker.py      # 공통: IMAP OTP 파서
│   ├── vpn_connector.py     # 공통: openfortivpn 비동기 연동 엔진
│   ├── autostart_windows.py # Windows용 자동실행 구성 도우미
│   └── logger.py            # 공통: 로거 모듈
├── run.sh                   # macOS 기동 셸 스크립트
├── run.bat                  # Windows 기동 배치 파일
├── setup.sh                 # macOS 설치 가이드 스크립트
├── setup.bat                # Windows 설치 가이드 스크립트
├── autostart.sh             # macOS 자동실행 구성 스크립트
├── requirements.txt         # 종속성 정의
├── README.md                # 설명서
└── CLAUDE.md                # 개발 지침
```

---

## 🛠️ 사전 준비 사항

### 1. openfortivpn 코어 설치
- **macOS**: `setup.sh` 실행 시 Homebrew를 통해 자동 설치됩니다.
- **Windows**: Windows용 `openfortivpn.exe` 바이너리를 직접 다운로드하여 프로젝트 폴더 내에 배치해야 동작합니다.
  - [openfortivpn Releases](https://github.com/adrienverge/openfortivpn/releases) 에서 다운로드받아 본 프로젝트 폴더에 넣어주세요.

### 2. 다음 / 카카오 메일 IMAP 활성화
메일을 프로그램에서 조회하기 위해 반드시 본인 이메일 설정에서 IMAP 서비스가 활성화되어 있어야 합니다.

* **다음 메일 설정 방법**:
  1. [Daum 메일](https://mail.daum.net) 로그인 ➔ 좌측 하단의 **'환경설정'** 클릭.
  2. 상단 메뉴의 **'IMAP/POP3'** 탭 선택.
  3. **'IMAP/SMTP 서비스'** 설정을 **'사용함'**으로 설정 후 저장.
* **주의 (카카오 / 다음 2단계 인증 사용자)**:
  - 2단계 인증을 사용 중인 경우, 본인의 일반 비밀번호 대신 카카오 계정 관리 페이지에서 **[보안 ➔ 2단계 인증 ➔ 앱 비밀번호]**를 생성하여 해당 앱 비밀번호를 이메일 암호 설정에 입력해야만 로그인이 가능합니다.

---

## 📥 설치 및 실행 방법

### 🍏 macOS 사용자
1. **설치 스크립트 실행** (Homebrew 설치 및 openfortivpn 권한 설정 포함):
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```
2. **실행**:
   ```bash
   ./run.sh
   ```
3. **로그인 시 자동 실행 등록** (LaunchAgent 등록):
   ```bash
   ./autostart.sh install
   ```

### 💻 Windows 사용자
1. **설치 스크립트 실행** (가상환경 구성 및 패키지 설치):
   `setup.bat` 파일을 더블클릭하여 실행합니다.
2. **실행**:
   `run.bat` 파일을 더블클릭하여 실행합니다. VPN 연결을 위해 **관리자 권한(UAC)** 승인이 요구됩니다.
3. **로그인 시 자동 실행 등록** (시작 프로그램 등록):
   가상환경이 활성화된 터미널 혹은 셸에서 다음을 실행합니다:
   ```cmd
   python src/autostart_windows.py install
   ```

---

## 💻 사용 가이드 (설정 및 연결)

1. **최초 1회 설정 등록**:
   아이콘을 클릭하고 **`Settings`**를 선택하면 로컬 웹 페이지가 열립니다. 자격 증명을 순서대로 등록합니다.
   * **VPN Host/Port**: 사내 VPN 게이트웨이 및 포트 (예: `vpn.company.com:443`)
   * **VPN Username/Password**: VPN 로그인 정보
   * **IMAP Host/Port**: 다음 메일 `imap.daum.net:993` 등
   * **Mail ID/Password**: 메일 로그인 정보 (2단계 인증자는 생성한 **앱 비밀번호**)
2. **VPN 연결 및 가동**:
   - 아이콘 클릭 ➔ **`Connect VPN`** 선택 ➔ 생체 인증(Touch ID / Windows Hello)을 수행합니다.
   - 인증 성공 시 자동으로 OTP 메일을 추적하여 기입 및 터널을 형성하며 상태바 색상이 🟢로 바뀝니다.
3. **VPN 수동 해제**:
   - 아이콘 클릭 ➔ **`Disconnect VPN`** 선택 시 안전하게 터널이 철거됩니다.
