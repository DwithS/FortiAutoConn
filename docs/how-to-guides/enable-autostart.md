# 로그인 시 자동 실행 등록하기

매번 터미널에서 `./run.sh`를 실행하지 않고, 맥북에 로그인하면 메뉴바 앱이 알아서 뜨도록 만드는 방법입니다.

## 등록하기

```bash
./autostart.sh install
```

macOS LaunchAgent(`~/Library/LaunchAgents/com.dailyfunding.fortiautoconn.plist`)를 등록하고, 등록 즉시 앱을 한 번 실행합니다. 이후로는 로그인할 때마다 자동으로 켜집니다.

앱이 크래시 등으로 비정상 종료되면 launchd가 자동으로 다시 띄웁니다. 메뉴바에서 **Quit**으로 정상 종료한 경우에는 다시 켜지지 않습니다.

## 등록 상태 확인하기

```bash
./autostart.sh status
```

등록 여부와 현재 실행 중인지를 보여줍니다.

## 해제하기

```bash
./autostart.sh uninstall
```

LaunchAgent 등록을 지우고, 현재 실행 중인 앱도 종료합니다.

## 관련 문서

- 설정 파일 경로 등 자세한 내용은 [명령어/스크립트 레퍼런스](../reference/commands.md)를 참고하세요.
