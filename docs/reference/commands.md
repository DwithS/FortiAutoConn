# 명령어 / 스크립트 레퍼런스

## 설치 및 실행

| 명령 | 동작 |
| --- | --- |
| `./setup.sh` | `openfortivpn`(Homebrew 자동 설치 포함), Python 의존성(`.venv`), `openfortivpn`/`route`에 대한 무암호 sudo 규칙을 설정. |
| `./run.sh` | `.venv/bin/python3`(없으면 시스템 `python3`)를 감지해, `com.dailyfunding.forti-auto`로 재서명한 별도 복사본 인터프리터(`forti-auto`)로 앱을 실행. Touch ID/Keychain 팝업에 `python3.12` 대신 `forti-auto`가 표시되게 하려는 목적. |
| `uv pip install -r requirements.txt` | uv로 의존성 설치 (대안). |
| `uv sync` | `uv.lock` 기준으로 의존성 동기화 (대안). |

## 로그인 자동 실행

| 명령 | 동작 |
| --- | --- |
| `./autostart.sh install` | LaunchAgent(`~/Library/LaunchAgents/com.dailyfunding.fortiautoconn.plist`) 등록 + 즉시 1회 기동. |
| `./autostart.sh uninstall` | LaunchAgent 등록 해제 + 실행 중인 앱 종료. |
| `./autostart.sh status` | 등록/실행 상태 확인. |

## 테스트

| 명령 | 동작 | 요구 사항 |
| --- | --- | --- |
| `python3 tests/test_parsing.py` (또는 `pytest tests/test_parsing.py`) | IMAP Modified UTF-7 인코딩, OTP 정규식, 폴더 바이트 매칭, OTP 메일 스캔 필터링 등 순수 함수 단위 테스트. | 없음 (오프라인, Touch ID 불필요) |
| `python3 tests/test_keychain.py` | Touch ID + Keychain 읽기/쓰기/삭제를 실제로 수행하는 대화형 스크립트. | Touch ID 하드웨어 |
| `python3 tests/test_mail.py` | 실제 IMAP 로그인 + 실시간 OTP 메일 폴링을 수행하는 대화형 스크립트. | Settings에 저장된 실제 메일 자격 증명 |

## 환경 변수

```bash
FORTI_DEBUG=1 ./run.sh
```

로그 레벨을 DEBUG로 올려 메일 폴링 타이밍 등 상세 로그를 노출합니다.
