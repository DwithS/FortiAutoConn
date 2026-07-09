import os
import sys
import time
import json
import html
import secrets
import subprocess
import ipaddress
import threading
import webbrowser
import signal
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from keychain_manager import KeychainManager
from mail_checker import MailChecker
from vpn_connector import VPNConnector
from logger import logger

class SettingsHTTPServer:
    def __init__(self, port, service_name, on_save_callback):
        self.port = port
        self.service_name = service_name
        self.on_save_callback = on_save_callback
        self.server = None
        self.token = secrets.token_urlsafe(32)

    def bind(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import urllib.parse

        class SettingsHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _host_allowed(self):
                host = self.headers.get("Host", "")
                port = self.server.server_port
                return host in (f"127.0.0.1:{port}", f"localhost:{port}")

            def _token_valid(self, supplied):
                return bool(supplied) and secrets.compare_digest(supplied, self.server.access_token)

            def _deny(self, code, message):
                self.send_response(code)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(message.encode("utf-8"))

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if not self._host_allowed():
                    self._deny(403, "Forbidden")
                    return
                if parsed.path != "/":
                    self._deny(404, "Not Found")
                    return
                token = (urllib.parse.parse_qs(parsed.query).get("token") or [""])[0]
                if not self._token_valid(token):
                    self._deny(403, "Forbidden: 설정 페이지는 트레이 아이콘의 Settings 메뉴를 통해서만 열 수 있습니다.")
                    return

                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()

                config = FortiAutoConnWinApp.load_config()
                esc = lambda v: html.escape(v or "", quote=True)
                vpn_host = esc(config.get("vpn_host"))
                vpn_port = esc(config.get("vpn_port") or "443")
                vpn_user = esc(config.get("vpn_user"))

                vpn_dns_bypass = config.get("vpn_dns_bypass") or "true"
                vpn_split_tunnel = config.get("vpn_split_tunnel") or "true"
                vpn_split_routes = esc(config.get("vpn_split_routes") or "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16")

                mail_host = esc(config.get("mail_host") or "imap.daum.net")
                mail_port = esc(config.get("mail_port") or "993")
                mail_user = esc(config.get("mail_user"))
                mail_folder = esc(config.get("mail_folder") or "INBOX")
                otp_sender = esc(config.get("otp_sender") or MailChecker.DEFAULT_OTP_SENDER)

                dns_checked = "checked" if vpn_dns_bypass == "true" else ""
                split_checked = "checked" if vpn_split_tunnel == "true" else ""
                split_display = "block" if vpn_split_tunnel == "true" else "none"
                form_token = esc(token)

                page_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FortiAutoConn 환경 설정 (Windows)</title>
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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
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
            max-width: 540px;
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
            margin-right: 5px;
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
        
        .switch-container {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: rgba(17, 17, 27, 0.35);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 12px;
            transition: all 0.3s ease;
        }}
        .switch-container:hover {{
            border-color: rgba(137, 180, 250, 0.25);
            background: rgba(17, 17, 27, 0.5);
        }}
        .switch-label {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            flex: 1;
            padding-right: 15px;
        }}
        .switch-title {{
            font-size: 0.88rem;
            font-weight: 600;
            color: var(--text-color);
        }}
        .switch-desc {{
            font-size: 0.74rem;
            color: var(--text-muted);
            font-weight: 300;
            line-height: 1.35;
        }}
        .switch {{
            position: relative;
            display: inline-block;
            width: 44px;
            height: 24px;
            flex-shrink: 0;
        }}
        .switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #313244;
            transition: .3s;
            border-radius: 24px;
        }}
        .slider:before {{
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: #cdd6f4;
            transition: .3s;
            border-radius: 50%;
        }}
        input:checked + .slider {{
            background-color: #a6e3a1;
        }}
        input:checked + .slider:before {{
            transform: translateX(20px);
            background-color: #11111b;
        }}
        .routes-input-container {{
            margin-top: 8px;
            padding: 14px;
            background: rgba(17, 17, 27, 0.4);
            border: 1px dashed rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            animation: slideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        @keyframes slideDown {{
            from {{ opacity: 0; transform: translateY(-10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
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
            <div class="subtitle">보안 게이트웨이 및 인증 메일 계정 설정 (Windows)</div>
        </div>
        <form action="/save" method="POST">
            <input type="hidden" name="token" value="{form_token}">
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
                    <input type="password" id="vpn_pass" name="vpn_pass" placeholder="기존 비밀번호 유지 시 빈 칸">
                </div>
            </div>

            <div class="section-title">🛠️ 인터넷 & 라우팅 고급 제어</div>
            
            <div class="switch-container">
                <div class="switch-label">
                    <span class="switch-title">DNS 자동 변조 방지 (우회)</span>
                    <span class="switch-desc">VPN 연결 시 외부 사이트가 먹통이 될 때 활성화합니다. 회사 DNS로 덮어쓰지 않고 로컬 DNS를 유지합니다.</span>
                </div>
                <label class="switch">
                    <input type="checkbox" id="vpn_dns_bypass" name="vpn_dns_bypass" value="true" {dns_checked}>
                    <span class="slider"></span>
                </label>
            </div>

            <div class="switch-container">
                <div class="switch-label">
                    <span class="switch-title">스플릿 터널링 (사내 대역 분리)</span>
                    <span class="switch-desc">일반 인터넷 트래픽 속도 개선 및 일반 사이트 차단 우회 시 활성화합니다. 지정된 사내망 IP 대역만 VPN으로 라우팅하고 나머지는 직접 연결합니다.</span>
                </div>
                <label class="switch">
                    <input type="checkbox" id="vpn_split_tunnel" name="vpn_split_tunnel" value="true" {split_checked}>
                    <span class="slider"></span>
                </label>
            </div>

            <div class="routes-input-container" id="routes_container" style="display: {split_display};">
                <label for="vpn_split_routes">사내망 IP 대역 (쉼표로 구분)</label>
                <input type="text" id="vpn_split_routes" name="vpn_split_routes" placeholder="10.0.0.0/8, 172.16.0.0/12" value="{vpn_split_routes}">
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
                    <input type="password" id="mail_pass" name="mail_pass" placeholder="기존 비밀번호 유지 시 빈 칸">
                </div>
                <div class="form-group">
                    <label for="otp_sender">인증 메일 발신자</label>
                    <input type="text" id="otp_sender" name="otp_sender" placeholder="인증 코드 메일의 발신 주소" value="{otp_sender}" required>
                </div>
            </div>

            <button type="submit" class="btn-submit">설정 정보 저장 및 등록</button>
        </form>
    </div>

    <script>
        document.getElementById('vpn_split_tunnel').addEventListener('change', function() {{
            var container = document.getElementById('routes_container');
            if (this.checked) {{
                container.style.display = 'block';
                document.getElementById('vpn_dns_bypass').checked = true;
            }} else {{
                container.style.display = 'none';
            }}
        }});
    </script>
</body>
</html>
"""
                self.wfile.write(page_html.encode("utf-8"))

            def do_POST(self):
                if not self._host_allowed():
                    self._deny(403, "Forbidden")
                    return
                if self.path == "/save":
                    try:
                        content_length = int(self.headers.get('Content-Length') or 0)
                    except ValueError:
                        content_length = 0
                    if content_length <= 0 or content_length > 1_000_000:
                        self._deny(400, "Bad Request")
                        return
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    params = urllib.parse.parse_qs(post_data)

                    data = {k: v[0].strip() for k, v in params.items()}

                    if not self._token_valid(data.get("token", "")):
                        self._deny(403, "Forbidden: 잘못된 접근입니다. 트레이 아이콘의 Settings 메뉴로 다시 열어 주세요.")
                        return

                    split_val = "true" if data.get("vpn_split_tunnel", "false") == "true" else "false"
                    errors = []

                    def _valid_port(v):
                        return v.isdigit() and 1 <= int(v) <= 65535

                    if not _valid_port(data.get("vpn_port", "")):
                        errors.append("VPN Port는 1~65535 사이의 숫자여야 합니다.")
                    if not _valid_port(data.get("mail_port", "")):
                        errors.append("IMAP Port는 1~65535 사이의 숫자여야 합니다.")
                    if split_val == "true":
                        for r in data.get("vpn_split_routes", "").split(","):
                            r = r.strip()
                            if not r:
                                continue
                            try:
                                ipaddress.ip_network(r, strict=False)
                            except ValueError:
                                errors.append(f"잘못된 사내망 IP 대역 형식입니다: {r} (올바른 예: 10.0.0.0/8)")

                    if errors:
                        self.send_response(400)
                        self.send_header("Content-type", "text/html; charset=utf-8")
                        self.end_headers()
                        error_items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
                        error_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>입력 오류</title>
<style>body{{background:#0f0f1a;color:#cdd6f4;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;}}
.card{{background:rgba(30,30,46,.8);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:40px;max-width:460px;}}
h1{{color:#f38ba8;margin-bottom:15px;font-size:1.3rem;}} ul{{line-height:1.8;padding-left:20px;}} a{{color:#89b4fa;}}</style></head>
<body><div class="card"><h1>⚠ 저장할 수 없습니다</h1><ul>{error_items}</ul>
<p><a href="javascript:history.back()">← 돌아가서 수정하기</a></p></div></body></html>"""
                        self.wfile.write(error_html.encode("utf-8"))
                        return
                    
                    dns_val = "true" if (data.get("vpn_dns_bypass", "false") == "true" or split_val == "true") else "false"

                    updates = {
                        "vpn_host": data.get("vpn_host", ""),
                        "vpn_port": data.get("vpn_port", ""),
                        "vpn_user": data.get("vpn_user", ""),
                        "vpn_dns_bypass": dns_val,
                        "vpn_split_tunnel": split_val,
                        "vpn_split_routes": data.get("vpn_split_routes", ""),
                        "mail_host": data.get("mail_host", ""),
                        "mail_port": data.get("mail_port", ""),
                        "mail_user": data.get("mail_user", ""),
                        "mail_folder": data.get("mail_folder", "INBOX"),
                        "otp_sender": data.get("otp_sender", ""),
                    }
                    if data.get("vpn_pass", ""):
                        updates["vpn_pass"] = data["vpn_pass"]
                    if data.get("mail_pass", ""):
                        updates["mail_pass"] = data["mail_pass"]
                    FortiAutoConnWinApp.save_config(updates)

                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()

                    success_html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>설정 완료</title>
    <style>
        body {
            background: #0f0f1a;
            color: #cdd6f4;
            font-family: sans-serif;
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
        <p>모든 자격 증명이 Windows 자격 증명 관리자에 안전하게 암호화 저장되었습니다.<br><br>이제 이 브라우저 창을 닫으셔도 좋습니다.</p>
    </div>
</body>
</html>
"""
                    self.wfile.write(success_html.encode("utf-8"))

                    if self.server.on_save_callback:
                        threading.Thread(target=self.server.on_save_callback).start()
                else:
                    self._deny(404, "Not Found")

        self.server = HTTPServer(('127.0.0.1', self.port), SettingsHandler)
        self.server.on_save_callback = self.on_save_callback
        self.server.access_token = self.token

    def serve(self):
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


class FortiAutoConnWinApp:
    SERVICE_NAME = "FortiAutoConn"
    CONFIG_ACCOUNT = "config"
    SECRET_FIELDS = {"vpn_pass", "mail_pass"}
    
    # Windows용 AppData 디렉토리 사용
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FortiAutoConn")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

    @classmethod
    def _read_local_config(cls):
        try:
            with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    @classmethod
    def _write_local_config(cls, data):
        os.makedirs(cls.CONFIG_DIR, exist_ok=True)
        with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def _read_secret_config(cls):
        raw = KeychainManager.get_password(cls.SERVICE_NAME, cls.CONFIG_ACCOUNT)
        try:
            return json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {}

    @classmethod
    def _write_secret_config(cls, data):
        KeychainManager.save_password(cls.SERVICE_NAME, cls.CONFIG_ACCOUNT, json.dumps(data))

    @classmethod
    def load_config(cls):
        local = cls._read_local_config()
        secret = cls._read_secret_config()
        merged = dict(local)
        merged.update(secret)
        return merged

    @classmethod
    def save_config(cls, updates):
        secret_updates = {k: v for k, v in updates.items() if k in cls.SECRET_FIELDS}
        plain_updates = {k: v for k, v in updates.items() if k not in cls.SECRET_FIELDS}

        if plain_updates:
            local = cls._read_local_config()
            local.update(plain_updates)
            cls._write_local_config(local)

        if secret_updates:
            secret = cls._read_secret_config()
            secret.update(secret_updates)
            cls._write_secret_config(secret)

        return cls.load_config()

    def __init__(self):
        self.connector = None
        self.cached_creds = None
        self.auto_reconnect_enabled = False
        self.reconnect_timer = None
        self.settings_server = None
        self._connect_lock = threading.Lock()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        
        # pystray 아이콘 객체 초기화
        self.icon = None
        self._init_systray()

    def _init_systray(self):
        # 🔴 상태로 최초 아이콘 생성
        red_icon = self._create_circle_icon("red")
        
        # 메뉴 구성
        self.menu_items = [
            item("Connect VPN", self.on_connect, enabled=True),
            item("Disconnect VPN", self.on_disconnect, enabled=False),
            item("Settings", self.on_settings),
            pystray.Menu.SEPARATOR,
            item("Quit", self.on_quit)
        ]
        
        self.icon = pystray.Icon(
            "FortiAutoConn",
            icon=red_icon,
            title="FortiAutoConn (Disconnected)",
            menu=pystray.Menu(*self.menu_items)
        )

    def _create_circle_icon(self, color):
        """Pillow를 이용해 트레이 아이콘에 표시할 컬러 원 이미지를 동적으로 생성합니다."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        color_map = {
            "red": (255, 75, 75, 255),     # 끊김
            "yellow": (255, 200, 0, 255),   # 연결 처리 중
            "green": (50, 205, 50, 255)     # 안전 연결 완료
        }
        c = color_map.get(color, (255, 75, 75, 255))
        draw.ellipse((8, 8, 56, 56), fill=c)
        return img

    def show_notification(self, title, subtitle, message):
        """winsdk.windows.ui.notifications API를 통해 Windows 10/11 네이티브 토스트 알림을 띄웁니다."""
        try:
            from winsdk.windows.ui.notifications import ToastNotificationManager, ToastNotification
            from winsdk.windows.data.xml.dom import XmlDocument
            
            toast_xml = f"""
            <toast>
                <visual>
                    <binding template="ToastGeneric">
                        <text>{title}</text>
                        <text>{subtitle}</text>
                        <text>{message}</text>
                    </binding>
                </visual>
            </toast>
            """
            xml_doc = XmlDocument()
            xml_doc.load_xml(toast_xml)
            notifier = ToastNotificationManager.create_toast_notifier("FortiAutoConn")
            notification = ToastNotification(xml_doc)
            notifier.show(notification)
        except Exception as e:
            logger.error(f"[Notification] Windows Toast 알림 송출 에러: {e}")

    def update_ui(self, status):
        logger.info(f"[App] update_ui 상태 변경 수신: {status}")
        
        if status == VPNConnector.STATUS_CONNECTED:
            # 초록색으로 아이콘 변경
            self.icon.icon = self._create_circle_icon("green")
            self.icon.title = "FortiAutoConn (Connected)"
            self._update_menu_state(connect_enabled=False, disconnect_enabled=True)
            self.show_notification("FortiAutoConn", "VPN 연결 성공", "업무용 VPN 망에 안전하게 연결되었습니다.")
            self.reconnect_attempts = 0
            
        elif status == VPNConnector.STATUS_CONNECTING:
            # 노란색으로 아이콘 변경
            self.icon.icon = self._create_circle_icon("yellow")
            self.icon.title = "FortiAutoConn (Connecting...)"
            self._update_menu_state(connect_enabled=False, disconnect_enabled=True)
            
        elif status == VPNConnector.STATUS_DISCONNECTED:
            # 빨간색으로 아이콘 변경
            self.icon.icon = self._create_circle_icon("red")
            self.icon.title = "FortiAutoConn (Disconnected)"
            self._update_menu_state(connect_enabled=True, disconnect_enabled=False)
            
            if self.auto_reconnect_enabled and self.cached_creds:
                self._handle_reconnect_flow("VPN 연결 해제됨", "VPN 연결이 세션 만료 등으로 분리되었습니다.")
                
        elif status == VPNConnector.STATUS_FAILED:
            self.icon.icon = self._create_circle_icon("red")
            self.icon.title = "FortiAutoConn (Connection Failed)"
            self._update_menu_state(connect_enabled=True, disconnect_enabled=False)

            reason = self.connector.failure_reason if self.connector else None
            fatal_messages = {
                VPNConnector.REASON_MAIL_AUTH: "메일 로그인이 거부되었습니다. Settings에서 메일 비밀번호(앱 비밀번호)를 확인해 주세요.",
                VPNConnector.REASON_VPN_AUTH: "VPN 비밀번호가 거부되었습니다. Settings에서 VPN 비밀번호를 확인해 주세요.",
                VPNConnector.REASON_SUDO: "관리자 무암호 권한이 설정되어 있지 않습니다.",
                VPNConnector.REASON_OTP: "OTP 코드가 반복 거부되었습니다. 메일함 폴더 설정과 인증 메일 수신 여부를 확인해 주세요.",
            }

            if reason in fatal_messages:
                self.auto_reconnect_enabled = False
                self.reconnect_attempts = 0
                if self.reconnect_timer:
                    self.reconnect_timer.cancel()
                logger.warning(f"[App] 재시도 불가 사유({reason}) 감지. 자동 재연결 중단.")
                self.show_notification("FortiAutoConn", "VPN 연결 실패 (자동 재연결 중단)", fatal_messages[reason])
            elif self.auto_reconnect_enabled and self.cached_creds:
                self._handle_reconnect_flow("VPN 연결 실패", "비밀번호 인증 오류 혹은 OTP 메일 수신 실패로 접속하지 못했습니다.")
            else:
                self.show_notification("FortiAutoConn", "VPN 연결 실패", "비밀번호 인증 오류 혹은 OTP 메일 수신 실패로 접속하지 못했습니다.")

    def _update_menu_state(self, connect_enabled, disconnect_enabled):
        """pystray 메뉴 아이템의 활성/비활성 상태를 동적으로 갱신합니다."""
        self.menu_items[0] = item("Connect VPN", self.on_connect, enabled=connect_enabled)
        self.menu_items[1] = item("Disconnect VPN", self.on_disconnect, enabled=disconnect_enabled)
        self.icon.menu = pystray.Menu(*self.menu_items)

    def _handle_reconnect_flow(self, title_msg, detail_msg):
        if self.reconnect_attempts < self.max_reconnect_attempts:
            backoff_delays = [10.0, 30.0, 60.0]
            delay = backoff_delays[self.reconnect_attempts]
            
            self.reconnect_attempts += 1
            logger.info(f"[App] 자동 재연결 시도 스케줄링 ({self.reconnect_attempts}/{self.max_reconnect_attempts}회째). 지연 시간: {delay}초")
            
            self.show_notification(
                "FortiAutoConn",
                title_msg,
                f"재연결을 시도합니다 ({self.reconnect_attempts}/{self.max_reconnect_attempts}회). {int(delay)}초 후 시작합니다."
            )
            self.trigger_auto_reconnect(delay)
        else:
            self.auto_reconnect_enabled = False
            self.reconnect_attempts = 0
            logger.warning("[App] 연속 3회 재시도 실패로 인해 자동 재연결 기능 안전을 위해 비활성화.")
            self.show_notification(
                "FortiAutoConn",
                "자동 재연결 비활성화",
                "연속 3회 재시도 실패로 계정 차단 방지를 위해 자동 재연결이 중단되었습니다."
            )

    def on_status_change(self, new_status):
        # pystray의 경우 직접 UI 갱신 가능하므로 바로 업데이트
        self.update_ui(new_status)

    def trigger_auto_reconnect(self, delay=10.0):
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            
        self.reconnect_timer = threading.Timer(delay, self._perform_reconnect)
        self.reconnect_timer.start()

    def _perform_reconnect(self):
        if not self.auto_reconnect_enabled or not self.cached_creds:
            logger.info("[App] 자동 재연결 수행 불가 상태 (플래그 혹은 자격 증명 없음).")
            return
            
        logger.info(f"[App] 백그라운드 자동 재접속 기동 실행... ({self.reconnect_attempts}/{self.max_reconnect_attempts})")

        if self.connector:
            self.connector.stop(notify=False)

        self.connector = self._build_connector(self.cached_creds)
        self.connector.start()

    def _build_connector(self, creds):
        mail_checker = MailChecker(
            host=creds["mail_host"],
            port=creds["mail_port"],
            username=creds["mail_user"],
            password=creds["mail_pass"],
            mailbox=creds.get("mail_folder", "INBOX"),
            otp_sender=creds.get("otp_sender")
        )
        return VPNConnector(
            host=creds["vpn_host"],
            port=creds["vpn_port"],
            username=creds["vpn_user"],
            password=creds["vpn_pass"],
            mail_checker=mail_checker,
            on_status_change=self.on_status_change,
            dns_bypass=(creds.get("vpn_dns_bypass") == "true"),
            split_tunnel=(creds.get("vpn_split_tunnel") == "true"),
            split_routes=creds.get("vpn_split_routes", "")
        )

    def on_connect(self, icon, item):
        """Connect VPN 트레이 메뉴 클릭 핸들러 (비동기 스레드 실행)"""
        if self.connector and self.connector.status in (VPNConnector.STATUS_CONNECTING, VPNConnector.STATUS_CONNECTED):
            return
        if not self._connect_lock.acquire(blocking=False):
            return

        logger.info("[App] 사용자가 Connect VPN을 호출했습니다.")
        self.reconnect_attempts = 0
        threading.Thread(target=self._bg_connect, daemon=True).start()

    def _bg_connect(self):
        try:
            # 1. Windows Hello 인증 호출
            if not KeychainManager.authenticate_touch_id("FortiVPN 보안 터널 형성을 위해 본인 생체정보 또는 PIN을 인증해 주세요."):
                logger.warning("[App] Windows Hello 인증 거부/취소.")
                self.show_notification("보안 인증 오류", "본인 인증 실패", "Windows Hello 본인인증이 취소되어 키체인 자격증명을 불러올 수 없습니다.")
                return

            # 2. 자격 증명 로드
            creds = FortiAutoConnWinApp.load_config()
            # 필수 값 확인 (비밀번호 포함)
            required_keys = ["vpn_host", "vpn_port", "vpn_user", "vpn_pass", "mail_host", "mail_port", "mail_user", "mail_pass"]
            if not all(creds.get(k) for k in required_keys):
                logger.warning("[App] 자격 증명 일부 누락.")
                self.show_notification("자격 증명 미설정", "설정 필요", "설정된 VPN 혹은 메일 계정 정보가 누락되었습니다. Settings에서 등록해 주세요.")
                self.on_settings(None, None)
                return

            self.cached_creds = creds
            self.auto_reconnect_enabled = True

            # 3. VPN 구동
            self.connector = self._build_connector(creds)
            self.connector.start()
        finally:
            self._connect_lock.release()

    def on_disconnect(self, icon, item):
        logger.info("[App] 사용자가 VPN 연결 해제를 호출했습니다.")
        self.auto_reconnect_enabled = False
        self.reconnect_attempts = 0
        
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            
        if self.connector:
            self.connector.stop()
            self.connector = None
            
        self.cached_creds = None
        self.show_notification("FortiAutoConn", "VPN 접속 종료 완료", "자동화 VPN 터널 연결이 정상 해제되었습니다.")

    def on_settings(self, icon, item):
        logger.info("[App] Settings 웹 설정창 진입 요청.")
        if self.settings_server:
            webbrowser.open(f"http://127.0.0.1:18372/?token={self.settings_server.token}")
            return

        def on_save_success():
            self.show_notification("FortiAutoConn", "설정 갱신 완료", "새로운 설정이 Windows 자격 증명 관리자에 안전하게 저장되었습니다.")
            logger.info("[App] 설정 저장 성공 콜백 수신. 웹 서버 소멸 대기...")
            time.sleep(1.0)
            if self.settings_server:
                self.settings_server.stop()
                self.settings_server = None
                logger.info("[App] 설정용 웹 서버가 안전하게 중지되었습니다.")

        server = SettingsHTTPServer(18372, self.SERVICE_NAME, on_save_success)
        try:
            server.bind()
        except OSError as e:
            logger.error(f"[App] 설정용 웹 서버 바인딩 실패 (Port 18372): {e}")
            self.show_notification(
                "FortiAutoConn",
                "설정 창 열기 실패",
                "127.0.0.1:18372 포트 바인딩에 실패했습니다. 타 프로그램이 사용 중인지 확인바랍니다."
            )
            return

        self.settings_server = server
        server_thread = threading.Thread(target=server.serve, daemon=True)
        server_thread.start()
        
        webbrowser.open(f"http://127.0.0.1:18372/?token={self.settings_server.token}")

    def on_quit(self, icon, item):
        logger.info("[App] 종료 요청 수신. 리소스 정리 후 프로그램을 정상 종료합니다.")
        self.terminate()
        self.icon.stop()

    def terminate(self):
        self.auto_reconnect_enabled = False
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        if self.connector:
            self.connector.stop()
        if self.settings_server:
            self.settings_server.stop()
        logger.info("[App] 모든 백그라운드 리소스 정리 완료.")

    def run(self):
        # pystray 트레이 루프 시작 (메인 스레드 대기)
        self.icon.run()

if __name__ == "__main__":
    # Windows 강제 종료 시그널(Ctrl+C, taskkill 등) 핸들러 등록
    app = FortiAutoConnWinApp()
    
    def signal_handler(signum, frame):
        logger.info(f"[FortiAutoConn] 종료 시그널({signum}) 감지.")
        app.terminate()
        if app.icon:
            app.icon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app.run()
