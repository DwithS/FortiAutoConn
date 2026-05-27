import threading
import pexpect
import time
import sys

class VPNConnector:
    STATUS_DISCONNECTED = "disconnected"
    STATUS_CONNECTING = "connecting"
    STATUS_CONNECTED = "connected"
    STATUS_FAILED = "failed"

    def __init__(self, host, port, username, password, mail_checker, on_status_change=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail_checker = mail_checker
        self.on_status_change = on_status_change
        
        self.status = self.STATUS_DISCONNECTED
        self.process = None
        self.thread = None
        self._stop_event = threading.Event()
        self.trusted_cert = None # 자동 감지된 게이트웨이 인증서 해시 저장용

    def set_status(self, new_status):
        self.status = new_status
        if self.on_status_change:
            self.on_status_change(new_status)

    def start(self):
        """VPN 연결을 비동기 백그라운드 스레드로 시작합니다."""
        if self.status in [self.STATUS_CONNECTING, self.STATUS_CONNECTED]:
            print("[VPNConnector] 이미 연결 시도 중이거나 연결된 상태입니다.")
            return

        self._stop_event.clear()
        self.set_status(self.STATUS_CONNECTING)
        self.thread = threading.Thread(target=self._run_vpn, daemon=True)
        self.thread.start()

    def stop(self):
        """VPN 연결을 해제하고 프로세스를 정리합니다."""
        print("[VPNConnector] VPN 연결 종료 프로세스 작동...")
        self._stop_event.set()
        
        # openfortivpn 프로세스 강제 종료
        if self.process:
            try:
                # pexpect child에 SIGTERM 전송
                self.process.terminate(force=True)
            except Exception as e:
                print(f"[VPNConnector] openfortivpn 프로세스 해제 에러: {e}")
        
        self.set_status(self.STATUS_DISCONNECTED)

    def _run_vpn(self):
        import re

        # 이미 자동 감지된 인증서 해시가 있다면 실행 인자에 포함하여 검증 에러 우회
        trusted_cert_flag = f" --trusted-cert {self.trusted_cert}" if self.trusted_cert else ""
        cmd = f"sudo openfortivpn {self.host}:{self.port} -u {self.username}{trusted_cert_flag}"
        print(f"[VPNConnector] openfortivpn 실행 명령: {cmd}")

        try:
            # pexpect를 사용한 터미널 프롬프트 실시간 제어
            # 인코딩 utf-8 설정 필수
            self.process = pexpect.spawn(cmd, encoding='utf-8', timeout=120)
            
            # 감시할 패턴 정의
            # 0: 비밀번호 요구 프롬프트
            # 1: 2차 인증(OTP / 메일 인증) 코드 요구 프롬프트
            # 2: 게이트웨이 인증서 서명 신뢰 여부 질문 Confirm [y/n]
            # 3: 터널 연결 성공 로그
            # 4: 프로세스 예상치 못한 종료 EOF
            # 5: 제한시간 초과 (10초 단위로 상태 이벤트 루프 갱신)
            patterns = [
                r"[Pp]assword:",
                r"(?:[Oo]ne-[Tt]ime|[Tt]wo-[Ff]actor|[Oo]tp|[Cc]ode|[Pp]asscode).*:",
                r"Confirm.*\(y/n\)",
                r"Tunnel is up and running",
                pexpect.EOF,
                pexpect.TIMEOUT
            ]

            while not self._stop_event.is_set():
                index = self.process.expect(patterns, timeout=12)
                
                if index == 0:
                    print("[VPNConnector] 1차 비밀번호 요구 프롬프트 감지. 암호 전송...")
                    self.process.sendline(self.password)
                    
                elif index == 1:
                    print("[VPNConnector] 2차 OTP 코드 요구 프롬프트 감지. 인증 메일 확인 중...")
                    # 1차 비밀번호 제출 후 다음/카카오 이메일로 발송된 최신 메일 OTP 조회
                    otp_code = self.mail_checker.fetch_latest_otp(max_wait_seconds=90)
                    if otp_code:
                        print(f"[VPNConnector] 메일에서 파싱된 OTP 적용 입력: {otp_code}")
                        self.process.sendline(otp_code)
                    else:
                        print("[VPNConnector] 메일 수신 실패 또는 OTP 파싱 타임아웃. VPN 연결을 취소합니다.")
                        self.stop()
                        self.set_status(self.STATUS_FAILED)
                        return

                elif index == 2:
                    print("[VPNConnector] 신뢰되지 않는 게이트웨이 인증서 경고 감지. 'y' 전송하여 자동 신뢰 허용...")
                    self.process.sendline("y")

                elif index == 3:
                    print("[VPNConnector] VPN 터널 연결 성공! (Tunnel is up and running)")
                    self.set_status(self.STATUS_CONNECTED)
                    break

                elif index == 4:
                    output = self.process.before
                    print(f"[VPNConnector] openfortivpn 프로세스가 초기 연결 중 예기치 않게 종료되었습니다.\n로그: {output}")
                    
                    # 💡 핵심 자가 복구: 신뢰할 수 없는 사내 인증서 에러 감지 시 sha256 해시를 추출하여 자동 우회 재시도
                    if "Gateway certificate validation failed" in output or "trusted-cert" in output:
                        cert_match = re.search(r"(?:trusted-cert\s*=\s*|--trusted-cert\s+)([0-9a-fA-F]{64})", output)
                        if not cert_match:
                            cert_match = re.search(r"sha256 digest:\s*([0-9a-fA-F]{64})", output)
                            
                        if cert_match:
                            detected_hash = cert_match.group(1)
                            # 중복 무한 재시도를 방지하기 위해 새로운 해시 감지 시에만 자동 갱신 및 재접속 구동
                            if detected_hash != self.trusted_cert:
                                print(f"[VPNConnector] 🛡️ 신뢰되지 않는 사내 게이트웨이 인증서 해시 자동 검출: {detected_hash}")
                                print("[VPNConnector] 해당 인증서를 화이트리스트에 임시 자동 추가하여 3초 후 안전 재접속을 구동합니다...")
                                self.trusted_cert = detected_hash
                                self.process.close()
                                time.sleep(3)
                                # 새로운 스레드로 무중단 자가 복구 연결 수행
                                threading.Thread(target=self._run_vpn, daemon=True).start()
                                return
                                
                    self.set_status(self.STATUS_FAILED)
                    return

                elif index == 5:
                    # 주기적인 루프 감시
                    pass

            # VPN 연결이 수립(STATUS_CONNECTED)된 후 연결 수명 감시 루프
            while not self._stop_event.is_set():
                if not self.process.isalive():
                    print("[VPNConnector] VPN 터널 세션이 유실되었습니다 (프로세스 종료).")
                    self.set_status(self.STATUS_DISCONNECTED)
                    break
                
                # 5초 간격으로 연결 활성화 지속 모니터링
                time.sleep(5)

        except Exception as e:
            print(f"[VPNConnector] VPN 구동 스레드 내부 오류: {e}")
            self.set_status(self.STATUS_FAILED)
            self.stop()
