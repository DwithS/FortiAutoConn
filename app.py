import rumps
import os
import sys
import time
import threading
from keychain_manager import KeychainManager
from mail_checker import MailChecker
from vpn_connector import VPNConnector

# rumps 디버깅 무시 (릴리즈용)
rumps.debug_mode(False)

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

    def update_ui(self, status):
        """VPNConnector의 상태 코드에 맞춰 메뉴바 UI 및 OS 알림을 송출합니다."""
        if status == VPNConnector.STATUS_CONNECTED:
            self.title = "🟢"
            self.menu_connect.set_callback(None)
            self.menu_disconnect.set_callback(self.on_disconnect)
            rumps.notification("FortiAutoConn", "VPN 연결 성공", "업무용 VPN 망에 안전하게 연결되었습니다.")
            
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
                rumps.notification("FortiAutoConn", "VPN 연결 해제됨", "VPN 연결이 세션 만료 등으로 분리되었습니다. 10초 후 자동 재접속을 시작합니다.")
                self.trigger_auto_reconnect()
                
        elif status == VPNConnector.STATUS_FAILED:
            self.title = "🔴"
            self.menu_connect.set_callback(self.on_connect)
            self.menu_disconnect.set_callback(None)
            rumps.notification("FortiAutoConn", "VPN 연결 실패", "비밀번호 인증 오류 혹은 OTP 메일 수신 실패로 접속하지 못했습니다.")
            
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
        
        # 캐싱된 접속정보를 사용하여 터치 ID 창을 추가로 띄우지 않고 자연스럽게 복구
        c = self.cached_creds
        mail_checker = MailChecker(
            host=c["mail_host"],
            port=c["mail_port"],
            username=c["mail_user"],
            password=c["mail_pass"]
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
        """Connect VPN 메뉴 버튼 클릭 이벤트 처리"""
        # 1. 지문인식(Touch ID) 또는 로컬 로그인 암호 확인 팝업 호출
        if not KeychainManager.authenticate_touch_id("FortiVPN 보안 터널 형성을 위해 본인 생체정보를 인증해 주세요."):
            rumps.alert("보안 인증 오류", "맥북 본인인증(Touch ID)이 차단되거나 취소되어 저장된 키체인 자격증명을 불러올 수 없습니다.")
            return

        # 2. 키체인 저장 정보 로드
        creds = self._load_credentials_from_keychain()
        if not creds:
            rumps.alert("자격 증명 미설정", "설정된 VPN 혹은 메일 계정 정보가 없습니다. 메뉴에서 'Settings'를 선택하여 최초 1회 등록해 주세요.")
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
            password=creds["mail_pass"]
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

    def on_disconnect(self, sender):
        """Disconnect VPN 메뉴 버튼 클릭 이벤트 처리 (수동 해제)"""
        # 명시적인 수동 해제이므로 자동 재연결 시스템을 비활성화 처리함
        self.auto_reconnect_enabled = False
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            
        if self.connector:
            self.connector.stop()
            self.connector = None
            
        self.cached_creds = None
        rumps.notification("FortiAutoConn", "VPN 접속 종료 완료", "자동화 VPN 터널 연결이 정상 해제되었습니다.")

    def on_settings(self, sender):
        """rumps standard prompt를 사용한 자격증명 정보 기입 및 키체인 등록"""
        # 1. VPN 게이트웨이 주소
        vpn_host_win = rumps.Window(
            message="접속할 VPN 서버 주소를 입력해 주세요.\n(예: vpn.company.com)",
            title="VPN Host",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "vpn_host") or ""
        )
        vpn_host_res = vpn_host_win.run()
        if not vpn_host_res.clicked: return
        vpn_host = vpn_host_res.text.strip()
        
        # 2. VPN 포트번호 (보통 SSL VPN은 443 사용)
        vpn_port_win = rumps.Window(
            message="VPN 포트 번호를 지정해 주세요.",
            title="VPN Port",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "vpn_port") or "443"
        )
        vpn_port_res = vpn_port_win.run()
        if not vpn_port_res.clicked: return
        vpn_port = vpn_port_res.text.strip()

        # 3. VPN ID
        vpn_user_win = rumps.Window(
            message="VPN 접속 로그인 계정(ID)을 입력해 주세요.",
            title="VPN Username",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "vpn_user") or ""
        )
        vpn_user_res = vpn_user_win.run()
        if not vpn_user_res.clicked: return
        vpn_user = vpn_user_res.text.strip()

        # 4. VPN 패스워드 (secure 모드로 암호 노출 숨김 처리)
        vpn_pass_win = rumps.Window(
            message="VPN 로그인 패스워드를 입력해 주세요.",
            title="VPN Password",
            default_text="",
            secure=True
        )
        vpn_pass_res = vpn_pass_win.run()
        if not vpn_pass_res.clicked: return
        vpn_pass = vpn_pass_res.text.strip()

        # 5. IMAP Host (Daum / Kakao 주소 예시 추천 안내)
        mail_host_win = rumps.Window(
            message="인증 메일이 수신되는 메일의 IMAP 서버 호스트명을 기입해 주세요.\n(다음메일: imap.daum.net / 카카오메일: imap.kakao.com)",
            title="IMAP Host",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "mail_host") or "imap.daum.net"
        )
        mail_host_res = mail_host_win.run()
        if not mail_host_res.clicked: return
        mail_host = mail_host_res.text.strip()

        # 6. IMAP SSL Port (기본 993)
        mail_port_win = rumps.Window(
            message="IMAP 포트 번호를 입력해 주세요.",
            title="IMAP Port",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "mail_port") or "993"
        )
        mail_port_res = mail_port_win.run()
        if not mail_port_res.clicked: return
        mail_port = mail_port_res.text.strip()

        # 7. 이메일 아이디(주소 전체)
        mail_user_win = rumps.Window(
            message="인증 메일을 받는 본인의 이메일 주소 전체를 기입해 주세요.\n(예: user@daum.net)",
            title="Mail ID",
            default_text=KeychainManager.get_password(self.SERVICE_NAME, "mail_user") or ""
        )
        mail_user_res = mail_user_win.run()
        if not mail_user_res.clicked: return
        mail_user = mail_user_res.text.strip()

        # 8. 이메일 비밀번호 (secure 모드)
        mail_pass_win = rumps.Window(
            message="해당 이메일의 로그인 패스워드(또는 전용 앱 2차 패스워드)를 입력해 주세요.",
            title="Mail Password",
            default_text="",
            secure=True
        )
        mail_pass_res = mail_pass_win.run()
        if not mail_pass_res.clicked: return
        mail_pass = mail_pass_res.text.strip()

        # 키체인에 일괄 기입 처리
        KeychainManager.save_password(self.SERVICE_NAME, "vpn_host", vpn_host)
        KeychainManager.save_password(self.SERVICE_NAME, "vpn_port", vpn_port)
        KeychainManager.save_password(self.SERVICE_NAME, "vpn_user", vpn_user)
        KeychainManager.save_password(self.SERVICE_NAME, "vpn_pass", vpn_pass)
        KeychainManager.save_password(self.SERVICE_NAME, "mail_host", mail_host)
        KeychainManager.save_password(self.SERVICE_NAME, "mail_port", mail_port)
        KeychainManager.save_password(self.SERVICE_NAME, "mail_user", mail_user)
        KeychainManager.save_password(self.SERVICE_NAME, "mail_pass", mail_pass)

        rumps.alert("설정 등록 완료", "입력하신 모든 정보가 macOS 시스템 Keychain에 안전하게 대칭 암호화 저장되었습니다.")

    def _load_credentials_from_keychain(self):
        """키체인 보안 풀에서 설정 정보 로드"""
        vpn_host = KeychainManager.get_password(self.SERVICE_NAME, "vpn_host")
        vpn_port = KeychainManager.get_password(self.SERVICE_NAME, "vpn_port")
        vpn_user = KeychainManager.get_password(self.SERVICE_NAME, "vpn_user")
        vpn_pass = KeychainManager.get_password(self.SERVICE_NAME, "vpn_pass")
        mail_host = KeychainManager.get_password(self.SERVICE_NAME, "mail_host")
        mail_port = KeychainManager.get_password(self.SERVICE_NAME, "mail_port")
        mail_user = KeychainManager.get_password(self.SERVICE_NAME, "mail_user")
        mail_pass = KeychainManager.get_password(self.SERVICE_NAME, "mail_pass")

        # 누락된 값이 하나라도 있으면 저장 정보 부재로 인식
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
            "mail_pass": mail_pass
        }

    def terminate(self):
        """애플리케이션 종료 시 터미널 정리 및 프로세스 안전 해제"""
        self.auto_reconnect_enabled = False
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        if self.connector:
            self.connector.stop()
        super(FortiAutoConnApp, self).terminate()

if __name__ == "__main__":
    app = FortiAutoConnApp()
    app.run()
