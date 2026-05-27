import rumps
import os
import sys
import time
import threading
import webbrowser
import signal
from AppKit import NSApplication
from keychain_manager import KeychainManager
from mail_checker import MailChecker
from vpn_connector import VPNConnector

# rumps 디버깅 무시 (릴리즈용)
rumps.debug_mode(False)

class SettingsHTTPServer:
    def __init__(self, port, service_name, on_save_callback):
        self.port = port
        self.service_name = service_name
        self.on_save_callback = on_save_callback
        self.server = None

    def start(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import urllib.parse

        # HTTPServer가 로컬 호스트에 바인딩되어 외부 접근을 원천 차단하고 보안을 강화합니다.
        class SettingsHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # 불필요한 HTTP 로그로 터미널이 어지러워지는 것을 방지
                pass

            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    
                    # 키체인에서 암호화 저장된 최신 값 로드 (보안 강화)
                    vpn_host = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "vpn_host") or ""
                    vpn_port = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "vpn_port") or "443"
                    vpn_user = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "vpn_user") or ""
                    mail_host = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "mail_host") or "imap.daum.net"
                    mail_port = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "mail_port") or "993"
                    mail_user = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "mail_user") or ""
                    mail_folder = KeychainManager.get_password(FortiAutoConnApp.SERVICE_NAME, "mail_folder") or "INBOX"

                    # 프리미엄 다크 글래스모피즘 테마의 반응형 HTML/CSS UI
                    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FortiAutoConn 환경 설정</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Noto+Sans+KR:wght@300;400;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0f0f1a;
            --panel-bg: rgba(30, 30, 46, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-color: #89b4fa;
            --accent-glow: rgba(137, 180, 250, 0.35);
            --text-color: #cdd6f4;
            --text-muted: #a6adc8;
            --success-color: #a6e3a1;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', 'Noto Sans KR', sans-serif;
        }}
        body {{
            background: radial-gradient(circle at 50% 50%, #1e1e2f 0%, var(--bg-color) 100%);
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow-x: hidden;
        }}
        .container {{
            background: var(--panel-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            width: 100%;
            max-width: 520px;
            padding: 40px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
            animation: fadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .header {{
            text-align: center;
            margin-bottom: 35px;
        }}
        .logo {{
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #89b4fa 0%, #b4befe 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }}
        .subtitle {{
            font-size: 0.95rem;
            color: var(--text-muted);
            font-weight: 300;
        }}
        .section-title {{
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--accent-color);
            margin: 25px 0 15px 0;
            display: flex;
            align-items: center;
            letter-spacing: 0.5px;
        }}
        .section-title::after {{
            content: '';
            flex: 1;
            height: 1px;
            background: linear-gradient(to right, rgba(137, 180, 250, 0.4), transparent);
            margin-left: 15px;
        }}
        .form-group {{
            margin-bottom: 18px;
        }}
        .form-row {{
            display: flex;
            gap: 15px;
        }}
        .form-row .form-group {{
            flex: 1;
        }}
        label {{
            display: block;
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 600;
        }}
        input {{
            width: 100%;
            background: rgba(17, 17, 27, 0.5);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 16px;
            color: var(--text-color);
            font-size: 0.95rem;
            outline: none;
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        }}
        input:focus {{
            border-color: var(--accent-color);
            box-shadow: 0 0 15px var(--accent-glow);
            background: rgba(17, 17, 27, 0.8);
        }}
        .btn-submit {{
            width: 100%;
            background: linear-gradient(135deg, #89b4fa 0%, #74c7ec 100%);
            border: none;
            border-radius: 14px;
            padding: 16px;
            color: #11111b;
            font-size: 1.05rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 30px;
            box-shadow: 0 8px 24px rgba(116, 199, 236, 0.25);
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        }}
        .btn-submit:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(116, 199, 236, 0.4);
            filter: brightness(1.1);
        }}
        .btn-submit:active {{
            transform: translateY(1px);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">FortiAutoConn</div>
            <div class="subtitle">보안 게이트웨이 및 인증 메일 계정 설정</div>
        </div>
        <form action="/save" method="POST">
            <div class="section-title">🔒 VPN Gateway 설정</div>
            <div class="form-row">
                <div class="form-group" style="flex: 2;">
                    <label for="vpn_host">VPN Host</label>
                    <input type="text" id="vpn_host" name="vpn_host" placeholder="vpn.company.com" value="{vpn_host}" required autofocus>
                </div>
                <div class="form-group" style="flex: 1;">
                    <label for="vpn_port">VPN Port</label>
                    <input type="text" id="vpn_port" name="vpn_port" placeholder="443" value="{vpn_port}" required>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="vpn_user">VPN Username</label>
                    <input type="text" id="vpn_user" name="vpn_user" placeholder="사번 또는 계정 ID" value="{vpn_user}" required>
                </div>
                <div class="form-group">
                    <label for="vpn_pass">VPN Password</label>
                    <input type="password" id="vpn_pass" name="vpn_pass" placeholder="••••••••" required>
                </div>
            </div>

            <div class="section-title">✉️ 인증 메일 IMAP 설정</div>
            <div class="form-row">
                <div class="form-group" style="flex: 2;">
                    <label for="mail_host">IMAP Host</label>
                    <input type="text" id="mail_host" name="mail_host" placeholder="imap.daum.net" value="{mail_host}" required>
                </div>
                <div class="form-group" style="flex: 1;">
                    <label for="mail_port">IMAP Port</label>
                    <input type="text" id="mail_port" name="mail_port" placeholder="993" value="{mail_port}" required>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group" style="flex: 2;">
                    <label for="mail_user">Mail Address / ID</label>
                    <input type="text" id="mail_user" name="mail_user" placeholder="이메일 주소 또는 ID" value="{mail_user}" required>
                </div>
                <div class="form-group" style="flex: 1;">
                    <label for="mail_folder">Mail Folder</label>
                    <input type="text" id="mail_folder" name="mail_folder" placeholder="INBOX" value="{mail_folder}" required>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="mail_pass">Mail Password</label>
                    <input type="password" id="mail_pass" name="mail_pass" placeholder="••••••••" required>
                </div>
            </div>

            <button type="submit" class="btn-submit">설정 정보 저장 및 등록</button>
        </form>
    </div>
</body>
</html>
"""
                    self.wfile.write(html.encode("utf-8"))

            def do_POST(self):
                if self.path == "/save":
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    params = urllib.parse.parse_qs(post_data)

                    # 파라미터 값 추출
                    data = {k: v[0].strip() for k, v in params.items()}

                    # 안전하게 키체인에 대칭 암호화 저장
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "vpn_host", data.get("vpn_host", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "vpn_port", data.get("vpn_port", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "vpn_user", data.get("vpn_user", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "vpn_pass", data.get("vpn_pass", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "mail_host", data.get("mail_host", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "mail_port", data.get("mail_port", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "mail_user", data.get("mail_user", ""))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "mail_folder", data.get("mail_folder", "INBOX"))
                    KeychainManager.save_password(FortiAutoConnApp.SERVICE_NAME, "mail_pass", data.get("mail_pass", ""))

                    # 성공 안내 페이지 송출
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()

                    success_html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>설정 완료</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;700&family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
    <style>
        body {
            background: #0f0f1a;
            color: #cdd6f4;
            font-family: 'Outfit', 'Noto Sans KR', sans-serif;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: rgba(30, 30, 46, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
        }
        h1 { color: #a6e3a1; margin-bottom: 15px; }
        p { color: #a6adc8; font-size: 0.95rem; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="card">
        <h1>✓ 설정 등록 완료</h1>
        <p>모든 자격 증명이 macOS Keychain에 안전하게 대칭 암호화 저장되었습니다.<br><br>이제 이 브라우저 창을 닫으셔도 좋습니다.</p>
    </div>
</body>
</html>
"""
                    self.wfile.write(success_html.encode("utf-8"))

                    # 서버 종료 및 후속 조치를 위해 콜백 실행
                    if self.server.on_save_callback:
                        threading.Thread(target=self.server.on_save_callback).start()

        # 대기 시간 없는 바인딩
        self.server = HTTPServer(('127.0.0.1', self.port), SettingsHandler)
        self.server.on_save_callback = self.on_save_callback
        self.server.serve_forever()

    def stop(self):
        if self.server:
            # shutdown()은 serve_forever() 루프를 안전하게 종료시킵니다.
            self.server.shutdown()
            self.server.server_close()

class FortiAutoConnApp(rumps.App):
    SERVICE_NAME = "FortiAutoConn"
    
    def __init__(self):
        # 🔴 상태로 최초 아이콘 로드 (메뉴바 상주용)
        super(FortiAutoConnApp, self).__init__(name="FortiAutoConn", title="🔴")
        
        # 메뉴바 우클릭 항목 구성
        self.menu_connect = rumps.MenuItem("Connect VPN", callback=self.on_connect)
        self.menu_disconnect = rumps.MenuItem("Disconnect VPN", callback=self.on_disconnect)
        self.menu_settings = rumps.MenuItem("Settings", callback=self.on_settings)
        
        self.menu = [
            self.menu_connect,
            self.menu_disconnect,
            self.menu_settings,
            None,  # 메뉴바 분리 구분선
        ]
        
        # 초기 버튼 상태 지정 (연결되지 않았을 때는 Disconnect 비활성화)
        self.menu_disconnect.set_callback(None)
        
        self.connector = None
        self.cached_creds = None      # 백그라운드 자동 재연결을 위해 메모리에만 세션 안전하게 유지
        self.auto_reconnect_enabled = False
        self.reconnect_timer = None
        self.settings_server = None

    def show_notification(self, title, subtitle, message):
        """macOS 내장 AppleScript를 활용하여 런타임 에러 없이 100% 안전하게 알림을 송출합니다."""
        try:
            # 특수 문자 에스케이프 처리
            safe_title = title.replace('"', '\\"')
            safe_subtitle = subtitle.replace('"', '\\"')
            safe_message = message.replace('"', '\\"')
            
            # osascript 명령 구성
            cmd = f'osascript -e \'display notification "{safe_message}" with title "{safe_title}" subtitle "{safe_subtitle}"\''
            os.system(cmd)
        except Exception as e:
            print(f"[Notification Error] 알림 송출 실패: {e}")

    def update_ui(self, status):
        """VPNConnector의 상태 코드에 맞춰 메뉴바 UI 및 OS 알림을 송출합니다."""
        if status == VPNConnector.STATUS_CONNECTED:
            self.title = "🟢"
            self.menu_connect.set_callback(None)
            self.menu_disconnect.set_callback(self.on_disconnect)
            self.show_notification("FortiAutoConn", "VPN 연결 성공", "업무용 VPN 망에 안전하게 연결되었습니다.")
            
        elif status == VPNConnector.STATUS_CONNECTING:
            self.title = "🟡"
            self.menu_connect.set_callback(None)
            self.menu_disconnect.set_callback(self.on_disconnect)
            
        elif status == VPNConnector.STATUS_DISCONNECTED:
            self.title = "🔴"
            self.menu_connect.set_callback(self.on_connect)
            self.menu_disconnect.set_callback(None)
            
            # 의도치 않은 접속 강제 해제 발생 시 (예: 8시간 세션 만료) 자동 재연결
            if self.auto_reconnect_enabled and self.cached_creds:
                self.show_notification("FortiAutoConn", "VPN 연결 해제됨", "VPN 연결이 세션 만료 등으로 분리되었습니다. 10초 후 자동 재접속을 시작합니다.")
                self.trigger_auto_reconnect()
                
        elif status == VPNConnector.STATUS_FAILED:
            self.title = "🔴"
            self.menu_connect.set_callback(self.on_connect)
            self.menu_disconnect.set_callback(None)
            self.show_notification("FortiAutoConn", "VPN 연결 실패", "비밀번호 인증 오류 혹은 OTP 메일 수신 실패로 접속하지 못했습니다.")
            
            if self.auto_reconnect_enabled and self.cached_creds:
                self.trigger_auto_reconnect()

    def on_status_change(self, new_status):
        """VPNConnector의 비동기 백그라운드 스레드에서 온 상태 변경 콜백을 메인 UI 스레드로 릴레이"""
        threading.Thread(target=self._safe_update_ui, args=(new_status,), daemon=True).start()

    def _safe_update_ui(self, status):
        self.update_ui(status)

    def trigger_auto_reconnect(self):
        """지정된 지연(10초) 이후 무인 백그라운드 재접속 스케줄링"""
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            
        self.reconnect_timer = threading.Timer(10.0, self._perform_reconnect)
        self.reconnect_timer.start()

    def _perform_reconnect(self):
        if not self.auto_reconnect_enabled or not self.cached_creds:
            return
            
        print("[App] 8시간 세션 만료 등에 대응하는 자동 백그라운드 재접속 구동...")
        
        c = self.cached_creds
        mail_checker = MailChecker(
            host=c["mail_host"],
            port=c["mail_port"],
            username=c["mail_user"],
            password=c["mail_pass"],
            mailbox=c.get("mail_folder", "INBOX")
        )
        
        self.connector = VPNConnector(
            host=c["vpn_host"],
            port=c["vpn_port"],
            username=c["vpn_user"],
            password=c["vpn_pass"],
            mail_checker=mail_checker,
            on_status_change=self.on_status_change
        )
        self.connector.start()

    def on_connect(self, sender):
        """Connect VPN 메뉴 버튼 클릭 이벤트 처리 (메인 스레드 대기 방지를 위해 백그라운드 스레드에서 비동기 처리)"""
        threading.Thread(target=self._bg_connect, daemon=True).start()

    def _bg_connect(self):
        # Touch ID 시스템 프롬프트가 포커스를 받을 수 있도록 앱 강제 활성화
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        
        # 1. 지문인식(Touch ID) 또는 로컬 로그인 암호 확인 팝업 호출
        if not KeychainManager.authenticate_touch_id("FortiVPN 보안 터널 형성을 위해 본인 생체정보를 인증해 주세요."):
            self._safe_alert("보안 인증 오류", "맥북 본인인증(Touch ID)이 차단되거나 취소되어 저장된 키체인 자격증명을 불러올 수 없습니다.")
            return

        # 2. 키체인 저장 정보 로드
        creds = self._load_credentials_from_keychain()
        if not creds:
            self._safe_alert("자격 증명 미설정", "설정된 VPN 혹은 메일 계정 정보가 없습니다. 메뉴에서 'Settings'를 선택하여 최초 1회 등록해 주세요.")
            self.on_settings(None)
            return

        # 3. 자동 재연결에 사용할 세션을 안전하게 메모리 캐시에 등록
        self.cached_creds = creds
        self.auto_reconnect_enabled = True
        
        # 4. VPN 시작
        mail_checker = MailChecker(
            host=creds["mail_host"],
            port=creds["mail_port"],
            username=creds["mail_user"],
            password=creds["mail_pass"],
            mailbox=creds.get("mail_folder", "INBOX")
        )
        
        self.connector = VPNConnector(
            host=creds["vpn_host"],
            port=creds["vpn_port"],
            username=creds["vpn_user"],
            password=creds["vpn_pass"],
            mail_checker=mail_checker,
            on_status_change=self.on_status_change
        )
        self.connector.start()

    def _safe_alert(self, title, message):
        """서브 스레드에서 호출 시 메인 UI를 블로킹하지 않도록 안전하게 대화상자 호출"""
        threading.Thread(target=lambda: rumps.alert(title, message), daemon=True).start()

    def on_disconnect(self, sender):
        """Disconnect VPN 메뉴 버튼 클릭 이벤트 처리 (수동 해제)"""
        self.auto_reconnect_enabled = False
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            
        if self.connector:
            self.connector.stop()
            self.connector = None
            
        self.cached_creds = None
        self.show_notification("FortiAutoConn", "VPN 접속 종료 완료", "자동화 VPN 터널 연결이 정상 해제되었습니다.")

    def on_settings(self, sender):
        """로컬 웹 서버를 스레드로 가동하고 브라우저를 띄워 설정을 안전하게 입력받습니다."""
        if self.settings_server:
            # 이미 서버가 돌고 있으면 브라우저 창만 한 번 더 띄워줍니다.
            webbrowser.open("http://127.0.0.1:18372/")
            return

        def on_save_success():
            # 저장 성공 시 알림 후 서버 해제
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.show_notification("FortiAutoConn", "설정 갱신 완료", "새로운 설정이 시스템 Keychain에 성공적으로 업데이트되었습니다.")
            
            # 약간의 딜레이를 주어 브라우저가 완료 응답 HTML을 모두 송출한 후 웹 서버를 소멸시킵니다.
            time.sleep(1.0)
            if self.settings_server:
                self.settings_server.stop()
                self.settings_server = None

        # 로컬 루프백 전용 웹 서버 구동
        self.settings_server = SettingsHTTPServer(18372, self.SERVICE_NAME, on_save_success)
        
        server_thread = threading.Thread(target=self.settings_server.start, daemon=True)
        server_thread.start()
        
        # 기본 브라우저 자동 호출
        webbrowser.open("http://127.0.0.1:18372/")

    def _load_credentials_from_keychain(self):
        """키체인 보안 풀에서 설정 정보 로드"""
        vpn_host = KeychainManager.get_password(self.SERVICE_NAME, "vpn_host")
        vpn_port = KeychainManager.get_password(self.SERVICE_NAME, "vpn_port")
        vpn_user = KeychainManager.get_password(self.SERVICE_NAME, "vpn_user")
        vpn_pass = KeychainManager.get_password(self.SERVICE_NAME, "vpn_pass")
        mail_host = KeychainManager.get_password(self.SERVICE_NAME, "mail_host")
        mail_port = KeychainManager.get_password(self.SERVICE_NAME, "mail_port")
        mail_user = KeychainManager.get_password(self.SERVICE_NAME, "mail_user")
        mail_folder = KeychainManager.get_password(self.SERVICE_NAME, "mail_folder") or "INBOX"
        mail_pass = KeychainManager.get_password(self.SERVICE_NAME, "mail_pass")

        if not all([vpn_host, vpn_port, vpn_user, vpn_pass, mail_host, mail_port, mail_user, mail_pass]):
            return None

        return {
            "vpn_host": vpn_host,
            "vpn_port": vpn_port,
            "vpn_user": vpn_user,
            "vpn_pass": vpn_pass,
            "mail_host": mail_host,
            "mail_port": mail_port,
            "mail_user": mail_user,
            "mail_folder": mail_folder,
            "mail_pass": mail_pass
        }

    def terminate(self):
        """애플리케이션 종료 시 터미널 정리 및 프로세스 안전 해제"""
        self.auto_reconnect_enabled = False
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        if self.connector:
            self.connector.stop()
        if self.settings_server:
            self.settings_server.stop()
        super(FortiAutoConnApp, self).terminate()

def sigint_handler(sig, frame):
    print("\n[FortiAutoConn] 사용자에 의해 강제 종료 시그널(SIGINT)이 감지되었습니다. 즉시 완전히 종료합니다.")
    # 터미널에서 Ctrl+C를 눌렀을 때 루프 대기 없이 즉각적으로 완벽하게 사멸 처리
    os._exit(0)

if __name__ == "__main__":
    # Ctrl+C 시그널 핸들러 연결
    signal.signal(signal.SIGINT, sigint_handler)
    
    app = FortiAutoConnApp()
    app.run()
