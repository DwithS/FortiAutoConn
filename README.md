# FortiAutoConn (FortiClient SSL-VPN 자동화 메뉴바 앱)

맥북에서 FortiClient VPN을 쓸 때 매번 **[연결 시도 → 인증메일 확인 → 6자리 OTP 입력]** 하던 번거로운 과정을 한 방에 자동화해 주는 macOS 메뉴바 상주 애플리케이션입니다.

`openfortivpn` 코어를 기반으로 하며, macOS **Touch ID**와 **Keychain**으로 자격 증명을 안전하게 보호하고, **다음/카카오 IMAP 메일 감시**로 인증 메일이 오는 즉시 OTP를 스스로 검출해 입력합니다. 세션이 만료되거나 게이트웨이 쪽 사유로 연결이 끊겨도, 지문 입력 없이 백그라운드에서 자동으로 재접속합니다.

## 🚀 주요 기능

- **네이티브 상태바 아이콘** — 🔴 끊김 / 🟡 연결·OTP 처리 중 / 🟢 연결됨
- **Touch ID + Keychain 연동** — 자격 증명이 코드나 파일에 평문으로 남지 않음
- **다음/카카오 메일 OTP 자동 감지** — 인증 메일 도착 즉시 6자리 코드를 자동 파싱·입력
- **스마트 자동 재연결** — 세션 만료 등으로 끊겨도 지문 재인증 없이 백그라운드에서 복구
- **무중단 세션 갱신(make-before-break)** — 스플릿 터널링 모드에서 8시간 만료 전에 미리 새 터널로 갈아탐

## 시작하기

처음 설치하는 경우, 아래 튜토리얼을 순서대로 따라 하면 됩니다.

👉 [튜토리얼: 처음부터 VPN 연결까지](docs/tutorials/getting-started.md)

## 📚 문서

이 저장소의 문서는 [Diátaxis](https://diataxis.fr) 체계로 정리되어 있습니다 — 지금 필요한 게 무엇인지에 따라 골라 보세요.

|                          | 이런 게 궁금할 때                    | 문서 |
| ------------------------ | ------------------------------------- | --- |
| 🎓 튜토리얼 (학습)        | 처음 써보는데 어떻게 시작하죠?        | [처음부터 VPN 연결까지](docs/tutorials/getting-started.md) |
| 🔧 How-to 가이드 (작업)   | OO를 하고 싶은데 어떻게 하나요?       | [로그인 시 자동 실행](docs/how-to-guides/enable-autostart.md) · [스플릿 터널링 설정](docs/how-to-guides/configure-split-tunnel.md) · [자꾸 끊기는 연결 진단](docs/how-to-guides/diagnose-frequent-disconnects.md) |
| 📖 레퍼런스 (조회)        | 그 설정 필드 이름이 정확히 뭐였지?    | [설정 필드](docs/reference/configuration.md) · [명령어/스크립트](docs/reference/commands.md) |
| 💡 설명 (이해)            | 왜 이렇게 만들었지? 원리가 뭐지?      | [아키텍처와 설계 결정](docs/explanation/architecture.md) |

전체 문서 지도는 [`docs/README.md`](docs/README.md)에 있습니다. 코드를 직접 수정할 AI 에이전트(Claude Code 등)를 위한 구현 노트는 별도로 [`CLAUDE.md`](CLAUDE.md)에 있습니다.
