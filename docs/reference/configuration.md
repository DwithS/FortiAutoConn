# 설정 필드 레퍼런스

Settings 화면(`http://127.0.0.1:18372`)에서 입력하는 값들과, 이 값들이 실제로 어디에 저장되는지의 전체 목록입니다.

## 저장 위치

| 종류 | 저장 위치 | 비고 |
| --- | --- | --- |
| `vpn_pass`, `mail_pass` | macOS Keychain (서비스명 `FortiAutoConn`, 계정명 `config`, JSON으로 인코딩된 단일 항목) | 두 비밀번호만 여기 저장됩니다. Keychain 접근 승인 팝업이 앱 전체에서 딱 한 번만 뜨도록, 비밀 항목을 이 하나로 몰아둔 것입니다. |
| 그 외 모든 필드 | `~/Library/Application Support/FortiAutoConn/config.json` (권한 `600`) | 평문 JSON 파일이며, 비밀번호는 절대 여기 섞이지 않습니다. |

`load_config()`는 첫 실행 시 예전 버전의 두 가지 구형 포맷(단일 통합 Keychain 블롭, 또는 필드별 개별 Keychain 항목)에서 자동으로 마이그레이션하고, 마이그레이션이 끝난 구형 항목은 삭제합니다.

## 필드 목록

| 필드 (내부 키) | Settings 화면 라벨 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `vpn_host` | VPN Host | — | VPN 서버 도메인/IP |
| `vpn_port` | VPN Port | — | VPN 포트 (보통 `443`) |
| `vpn_user` | VPN Username | — | VPN 로그인 아이디 |
| `vpn_pass` | VPN Password | — | VPN 로그인 비밀번호 (Keychain) |
| `vpn_dns_bypass` | VPN DNS Bypass | `false` | `true`면 `openfortivpn`에 `--pppd-no-peerdns --no-dns`를 붙여 DNS 서버 덮어쓰기를 막음. 스플릿 터널링을 켜면 자동으로 강제 `true`가 됨. |
| `vpn_split_tunnel` | VPN Split Tunnel | `false` | `true`면 `--no-routes`를 붙이고, `vpn_split_routes`에 적힌 대역만 수동으로 라우팅에 등록. |
| `vpn_split_routes` | VPN Split Routes | (빈 값) | 쉼표로 구분한 CIDR 목록 (예: `10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16`). `vpn_split_tunnel`이 켜져 있을 때만 쓰임. |
| `mail_host` | IMAP Host | — | 다음 `imap.daum.net` / 카카오 `imap.kakao.com` |
| `mail_port` | IMAP Port | — | 보통 `993` |
| `mail_user` | Mail ID | — | 메일 전체 주소 |
| `mail_pass` | Mail Password | — | 메일 로그인 비밀번호, 2단계 인증자는 앱 비밀번호 (Keychain) |
| `mail_folder` | Mail Folder | `INBOX` | 인증 메일이 오는 폴더명 (한글 폴더명도 지원) |
| `otp_sender` | (설정 화면에 노출, 기본값은 코드 상수) | `it@daily-funding.com` | 인증 메일 발신자 주소. 이 주소로부터 온 메일만 OTP 후보로 검사함. |

## 관련 상수 (코드에 하드코딩, 설정 화면에는 없음)

| 상수 | 위치 | 값 | 의미 |
| --- | --- | --- | --- |
| `VPNConnector.OTP_WAIT_SECONDS` | `vpn_connector.py` | `75`초 | 한 번의 연결 시도에서 OTP 메일을 기다리는 최대 시간. |
| `MailChecker.OTP_VALIDITY_SECONDS` | `mail_checker.py` | `60`초 | FortiToken 메일 OTP의 실제 유효 수명 (발송 시점 기준). |
| `VPNConnector.HEALTHCHECK_INTERVAL_SECONDS` | `vpn_connector.py` | `5`초 | 연결 중 ppp 인터페이스 상태를 확인하는 주기. |
| `VPNConnector.HEALTHCHECK_FAILURE_THRESHOLD` | `vpn_connector.py` | `3`회 연속 | 순간적인 링크 흔들림과 실제 세션 유실을 구분하는 임계치. |
| `VPNConnector.IDLE_KEEPALIVE_INTERVAL_SECONDS` | `vpn_connector.py` | `60`초 | 게이트웨이의 트래픽 기준 유휴 타임아웃을 피하기 위한 킵얼라이브 핑 주기. |
| `FortiAutoConnApp.SESSION_LIFETIME_SECONDS` | `app.py` | `8`시간 | FortiGate 세션 만료로 가정하는 시간. |
| `FortiAutoConnApp.SESSION_REFRESH_MARGIN_SECONDS` | `app.py` | `10`분 | 만료 몇 분 전에 무중단 세션 갱신(make-before-break)을 시작할지. |

## 환경 변수

| 변수 | 효과 |
| --- | --- |
| `FORTI_DEBUG` | 값이 설정되어 있으면(예: `FORTI_DEBUG=1`) 로그 레벨을 DEBUG로 올려, 메일 폴링 타이밍 등 평소 숨겨진 상세 로그를 노출. |

## 로그/로컬 서버

| 항목 | 값 |
| --- | --- |
| 로그 파일 | `logs/fortiautoconn.log` (5MB × 5개 롤링 백업) |
| Settings 로컬 웹 서버 | `http://127.0.0.1:18372` (loopback 전용, 요청마다 랜덤 토큰 필요) |
| LaunchAgent plist | `~/Library/LaunchAgents/com.dailyfunding.fortiautoconn.plist` |
