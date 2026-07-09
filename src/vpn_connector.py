import sys
import threading
import time
import re
import subprocess
import ipaddress
import queue
from logger import logger

# macOS에서만 pexpect 임포트
if sys.platform == "darwin":
    import pexpect
else:
    pexpect = None

class WindowsProcessWrapper:
    """
    Windows 환경에서 pexpect.spawn을 모방하기 위한 subprocess.Popen 래퍼.
    표준 출력 스트림을 스레드로 안전하게 비동기 큐에 쌓고, expect 요청 시 패턴을 대조합니다.
    """
    def __init__(self, cmd, args, timeout=120):
        # 윈도우에서 PATH에 openfortivpn.exe가 있거나 로컬에 있을 수 있음.
        # list 형태의 명령을 subprocess에 맞게 결합 (윈도우 셸 호환성 고려)
        full_cmd = [cmd] + args
        logger.info(f"[WindowsProcessWrapper] 프로세스 시작: {' '.join(full_cmd)}")
        self.process = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # stderr도 stdout으로 통합
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        self.queue = queue.Queue()
        self.buffer = ""
        self.before = ""
        self.thread = threading.Thread(target=self._read_output, daemon=True)
        self.thread.start()

    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ''):
                self.queue.put(line)
        except Exception as e:
            logger.error(f"[WindowsProcessWrapper] 읽기 스레드 에러: {e}")
        finally:
            self.process.stdout.close()

    def expect(self, patterns, timeout=10):
        """
        큐에서 새로운 출력이 들어올 때마다 버퍼에 붙여 regex 패턴들과 대조합니다.
        대조 성공 시 매칭된 인덱스를 반환하며, EOF/TIMEOUT에 맞춰 응답합니다.
        """
        start_time = time.time()
        # pexpect 패턴 상수 매핑
        EOF_INDEX = -1
        TIMEOUT_INDEX = -1
        for i, pat in enumerate(patterns):
            if pat == (pexpect.EOF if pexpect else -1):
                EOF_INDEX = i
            elif pat == (pexpect.TIMEOUT if pexpect else -2):
                TIMEOUT_INDEX = i

        while True:
            # 1) 현재 버퍼에 매칭되는 패턴이 있는지 검사
            for i, pattern in enumerate(patterns):
                if isinstance(pattern, str):
                    match = re.search(pattern, self.buffer, re.IGNORECASE)
                    if match:
                        # 매칭된 부분 이전의 텍스트 보관 (pexpect.before 모방)
                        self.before = self.buffer[:match.start()]
                        # 매칭된 부분 이후의 버퍼만 유지
                        self.buffer = self.buffer[match.end():]
                        return i

            # 2) 프로세스가 이미 종료되었는지 체크
            if self.process.poll() is not None:
                # 더 이상 읽을 데이터가 큐에 없다면 EOF 처리
                if self.queue.empty():
                    self.before = self.buffer
                    if EOF_INDEX != -1:
                        return EOF_INDEX
                    raise Exception("Process terminated unexpectedly (EOF)")

            # 3) 큐에서 다음 데이터 대기 (논블로킹 타임아웃 감시)
            time_left = timeout - (time.time() - start_time)
            if time_left <= 0:
                if TIMEOUT_INDEX != -1:
                    return TIMEOUT_INDEX
                raise Exception("Timeout waiting for pattern")

            try:
                # 0.1초씩 끊어서 대기함으로써 스톱 이벤트나 타임아웃 기한 체크
                line = self.queue.get(timeout=0.1)
                self.buffer += line
            except queue.Empty:
                continue

    def sendline(self, data):
        if self.process.stdin:
            try:
                self.process.stdin.write(data + "\n")
                self.process.stdin.flush()
            except Exception as e:
                logger.error(f"[WindowsProcessWrapper] 입력 전달 에러: {e}")

    def isalive(self):
        return self.process.poll() is None

    def close(self):
        self.terminate()

    def terminate(self, force=True):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


class VPNConnector:
    STATUS_DISCONNECTED = "disconnected"
    STATUS_CONNECTING = "connecting"
    STATUS_CONNECTED = "connected"
    STATUS_FAILED = "failed"

    REASON_MAIL_AUTH = "mail_auth"
    REASON_VPN_AUTH = "vpn_auth"
    REASON_SUDO = "sudo"
    REASON_OTP = "otp"

    def __init__(self, host, port, username, password, mail_checker, on_status_change=None, dns_bypass=False, split_tunnel=False, split_routes=""):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail_checker = mail_checker
        self.on_status_change = on_status_change

        self.dns_bypass = dns_bypass
        self.split_tunnel = split_tunnel
        self.split_routes = split_routes

        if self.split_tunnel and not self.dns_bypass:
            logger.info("[VPNConnector] 스플릿 터널링 활성 감지: 인터넷 끊김 방지를 위해 DNS 자동 변조 방지(우회)를 함께 활성화합니다.")
            self.dns_bypass = True

        self.status = self.STATUS_DISCONNECTED
        self.process = None
        self.thread = None
        self._stop_event = threading.Event()
        self.trusted_cert = None
        self.failure_reason = None
        self._active_ppp_if = None  # macOS: 인터페이스명, Windows: 할당된 가상 IP주소
        self._mail_verified = False

    def set_status(self, new_status):
        if new_status == self.status:
            return
        self.status = new_status
        if self.on_status_change:
            self.on_status_change(new_status)

    def start(self):
        if self.status in [self.STATUS_CONNECTING, self.STATUS_CONNECTED]:
            logger.warning("[VPNConnector] 이미 연결 시도 중이거나 연결된 상태입니다.")
            return

        self._stop_event.clear()
        self.failure_reason = None
        self.set_status(self.STATUS_CONNECTING)
        self.thread = threading.Thread(target=self._run_vpn, daemon=True)
        self.thread.start()

    def stop(self, notify=True):
        logger.info("[VPNConnector] VPN 연결 종료 프로세스 작동...")
        self._stop_event.set()
        self._terminate_process()
        if notify:
            self.set_status(self.STATUS_DISCONNECTED)
        else:
            self.status = self.STATUS_DISCONNECTED

    def _terminate_process(self):
        if self.process:
            try:
                self.process.terminate(force=True)
            except Exception as e:
                logger.error(f"[VPNConnector] openfortivpn 프로세스 해제 에러: {e}")

    def _fail(self, reason=None):
        self.failure_reason = reason
        self._stop_event.set()
        self._terminate_process()
        self.set_status(self.STATUS_FAILED)

    def _run_vpn(self):
        # 0. 메일 로그인 사전 점검
        if not self._mail_verified:
            if not self.mail_checker.verify_login():
                logger.error("[VPNConnector] 메일 로그인 사전 점검 실패. 불필요한 인증 메일 발송을 막기 위해 VPN 인증을 시작하지 않습니다.")
                self._fail(self.REASON_MAIL_AUTH)
                return
            self._mail_verified = True

        # OS별 명령어 구성
        is_windows = (sys.platform == "win32")
        
        args = []
        if not is_windows:
            # macOS는 sudo -n 사용
            cmd = "sudo"
            args = ["-n", "openfortivpn", f"{self.host}:{self.port}", "-u", str(self.username)]
        else:
            # Windows는 이미 관리자 권한이 유도되므로 바로 openfortivpn 호출
            cmd = "openfortivpn"
            args = [f"{self.host}:{self.port}", "-u", str(self.username)]

        if self.trusted_cert:
            args += ["--trusted-cert", self.trusted_cert]
        if self.dns_bypass:
            args += ["--pppd-no-peerdns", "--no-dns"]
        if self.split_tunnel:
            args.append("--no-routes")
            
        logger.info(f"[VPNConnector] openfortivpn 실행 명령: {cmd} {' '.join(args)}")

        password_prompts = 0
        otp_prompts = 0

        try:
            # OS별 프로세스 스폰 처리
            if is_windows:
                self.process = WindowsProcessWrapper(cmd, args)
            else:
                self.process = pexpect.spawn(cmd, args, encoding='utf-8', timeout=120)

            # 감시할 패턴 정의
            patterns = [
                r"[Pp]assword:",
                r"(?:[Oo]ne-[Tt]ime|[Tt]wo-[Ff]actor|[Oo]tp|[Cc]ode|[Pp]asscode).*:",
                r"Confirm.*\(y/n\)",
                r"Tunnel is up and running",
                pexpect.EOF if pexpect else -1,
                pexpect.TIMEOUT if pexpect else -2
            ]

            while not self._stop_event.is_set():
                index = self.process.expect(patterns, timeout=12)

                if index == 0:
                    password_prompts += 1
                    if password_prompts > 1:
                        logger.error("[VPNConnector] VPN 비밀번호가 거부되어 재요구되었습니다. 계정 잠금 방지를 위해 즉시 중단합니다.")
                        self._fail(self.REASON_VPN_AUTH)
                        return
                    logger.info("[VPNConnector] 1차 비밀번호 요구 프롬프트 감지. 암호 전송...")
                    self.process.sendline(self.password)

                elif index == 1:
                    otp_prompts += 1
                    if otp_prompts > 2:
                        logger.error("[VPNConnector] OTP가 반복 거부되었습니다. 인증 메일 남발 방지를 위해 중단합니다.")
                        self._fail(self.REASON_OTP)
                        return
                    logger.info("[VPNConnector] 2차 OTP 코드 요구 프롬프트 감지. 인증 메일 확인 중...")
                    otp_code = self.mail_checker.fetch_latest_otp(max_wait_seconds=90)
                    if otp_code:
                        masked = otp_code[:1] + "*" * (len(otp_code) - 1)
                        logger.info(f"[VPNConnector] 메일에서 파싱된 OTP 적용 입력: {masked}")
                        self.process.sendline(otp_code)
                    else:
                        reason = self.REASON_MAIL_AUTH if getattr(self.mail_checker, "auth_failed", False) else None
                        logger.warning("[VPNConnector] 메일 수신 실패 또는 OTP 파싱 타임아웃. VPN 연결을 취소합니다.")
                        self._fail(reason)
                        return

                elif index == 2:
                    logger.info("[VPNConnector] 신뢰되지 않는 게이트웨이 인증서 경고 감지. 'y' 전송하여 자동 신뢰 허용...")
                    self.process.sendline("y")

                elif index == 3:
                    logger.info("[VPNConnector] VPN 터널 연결 성공! (Tunnel is up and running)")
                    self._active_ppp_if = self._get_active_ppp_interface()
                    if self.split_tunnel:
                        self._apply_split_routing(self._active_ppp_if)
                    self.set_status(self.STATUS_CONNECTED)
                    break

                elif index == 4:
                    output = self.process.before or ""
                    logger.error(f"[VPNConnector] openfortivpn 프로세스가 초기 연결 중 예기치 않게 종료되었습니다.\n로그: {output}")

                    if "sudo:" in output and ("password is required" in output or "암호가 필요" in output):
                        logger.error("[VPNConnector] sudo 무암호 권한이 설정되어 있지 않습니다. ./setup.sh 를 다시 실행해 주세요.")
                        self._fail(self.REASON_SUDO)
                        return

                    if "Gateway certificate validation failed" in output or "trusted-cert" in output:
                        cert_match = re.search(r"(?:trusted-cert\s*=\s*|--trusted-cert\s+)([0-9a-fA-F]{64})", output)
                        if not cert_match:
                            cert_match = re.search(r"sha256 digest:\s*([0-9a-fA-F]{64})", output)

                        if cert_match:
                            detected_hash = cert_match.group(1)
                            if detected_hash != self.trusted_cert:
                                logger.info(f"[VPNConnector] 🛡️ 신뢰되지 않는 사내 게이트웨이 인증서 해시 자동 검출: {detected_hash}")
                                logger.info("[VPNConnector] 해당 인증서를 화이트리스트에 임시 자동 추가하여 3초 후 안전 재접속을 구동합니다...")
                                self.trusted_cert = detected_hash
                                self.process.close()
                                if self._stop_event.wait(3):
                                    return
                                threading.Thread(target=self._run_vpn, daemon=True).start()
                                return

                    if "Could not authenticate" in output or "Authentication failed" in output:
                        self._fail(self.REASON_VPN_AUTH)
                        return

                    self._fail()
                    return

                elif index == 5:
                    pass

            while not self._stop_event.is_set():
                process_alive = self.process.isalive()
                tunnel_up = self._is_ppp_interface_up(self._active_ppp_if)

                if not process_alive or not tunnel_up:
                    logger.warning(
                        f"[VPNConnector] VPN 터널 세션이 유실되었습니다 "
                        f"(프로세스 생존: {process_alive}, 터널 인터페이스/IP 정상: {tunnel_up})."
                    )
                    self.set_status(self.STATUS_DISCONNECTED)
                    break

                self._stop_event.wait(5)

        except Exception as e:
            logger.error(f"[VPNConnector] VPN 구동 스레드 내부 오류: {e}")
            self._fail()

    def _get_active_ppp_interface(self, wait_seconds=10):
        """
        활성 VPN 인터페이스명(macOS) 또는 할당된 가상 IP주소(Windows)를 반환합니다.
        """
        is_windows = (sys.platform == "win32")
        deadline = time.time() + wait_seconds
        
        while True:
            try:
                if not is_windows:
                    res = subprocess.check_output(["ifconfig"], encoding="utf-8")
                    interfaces = re.findall(r"(ppp\d+): flags=.*<UP,POINTOPOINT,RUNNING", res)
                    if interfaces:
                        return interfaces[0]
                else:
                    # Windows: ipconfig 결과에서 할당된 가상 IP 파싱
                    vpn_ip = self._get_windows_vpn_ip()
                    if vpn_ip:
                        return vpn_ip
            except Exception as e:
                logger.error(f"[VPNConnector] 활성 인터페이스 탐색 중 에러: {e}")

            if time.time() >= deadline:
                if not is_windows:
                    logger.warning("[VPNConnector] 활성 ppp 인터페이스를 찾지 못해 기본값 ppp0을 사용합니다.")
                    return "ppp0"
                else:
                    logger.warning("[VPNConnector] Windows VPN 가상 IP를 찾지 못해 기본 루프백(127.0.0.1)으로 리턴합니다.")
                    return "127.0.0.1"
            time.sleep(0.5)

    def _get_windows_vpn_ip(self):
        """ipconfig 출력에서 VPN 가상 어댑터에 할당된 IPv4 주소를 검출합니다."""
        try:
            output = subprocess.check_output(["ipconfig"], encoding="cp949", errors="ignore")
        except Exception:
            try:
                output = subprocess.check_output(["ipconfig"], encoding="utf-8", errors="ignore")
            except Exception:
                return None

        lines = output.split('\n')
        is_vpn_section = False
        for line in lines:
            # 윈도우 한글/영문 환경에서 VPN 어댑터 영역 감지
            if any(k in line.lower() for k in ["ppp", "forti", "ssl", "tap", "virtual"]):
                is_vpn_section = True
            elif is_vpn_section and ("IPv4" in line or "IP 주소" in line):
                match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                if match:
                    return match.group(1)
            elif is_vpn_section and len(line.strip()) > 0 and not line.startswith(" ") and not line.startswith("\t"):
                # 다른 네트워크 어댑터 제목줄이 다시 시작되면 섹션 종료
                is_vpn_section = False
        return None

    def _is_ppp_interface_up(self, ifname_or_ip):
        """인터페이스(macOS) 또는 가상 IP(Windows)가 활성 상태인지 확인합니다."""
        if not ifname_or_ip:
            return False
        
        is_windows = (sys.platform == "win32")
        try:
            if not is_windows:
                res = subprocess.check_output(["ifconfig", ifname_or_ip], encoding="utf-8", stderr=subprocess.DEVNULL)
                return bool(re.search(r"flags=.*<UP,POINTOPOINT,RUNNING", res))
            else:
                # Windows: 가상 IP가 여전히 ipconfig 상에 남아있는지 확인
                current_ip = self._get_windows_vpn_ip()
                return current_ip == ifname_or_ip
        except subprocess.CalledProcessError:
            return False
        except Exception as e:
            logger.error(f"[VPNConnector] 인터페이스/IP({ifname_or_ip}) 상태 확인 중 에러: {e}")
            return True

    def _apply_split_routing(self, ppp_if_or_ip=None):
        if not self.split_routes:
            logger.info("[VPNConnector] 스플릿 라우팅 대역이 비어 있어 등록을 생략합니다.")
            return

        is_windows = (sys.platform == "win32")
        if not ppp_if_or_ip:
            ppp_if_or_ip = self._get_active_ppp_interface()
            
        routes = [r.strip() for r in self.split_routes.split(",") if r.strip()]
        logger.info(f"[VPNConnector] 🛠️ 스플릿 터널링 가동: 대상 {ppp_if_or_ip} 기준으로 정적 라우팅을 등록합니다...")

        has_error = False
        for route in routes:
            try:
                net = ipaddress.ip_network(route, strict=False)
            except ValueError:
                logger.warning(f"[VPNConnector] ⚠️ 잘못된 IP 대역 형식이라 건너뜁니다: {route!r} (올바른 예: 10.0.0.0/8)")
                has_error = True
                continue

            if not is_windows:
                route_cmd = ["sudo", "-n", "route", "add", "-net", route, "-interface", ppp_if_or_ip]
            else:
                # Windows: route add <network> mask <netmask> <vpn_ip>
                # Windows에서는 sudo가 불필요 (이미 관리자 권한)
                route_cmd = ["route", "add", str(net.network_address), "mask", str(net.netmask), ppp_if_or_ip]

            logger.info(f"[VPNConnector] 라우팅 등록 실행: {' '.join(route_cmd)}")
            ret = subprocess.call(route_cmd)
            if ret != 0:
                logger.warning(f"[VPNConnector] ⚠️ 라우팅 등록 실패(반환 코드 {ret}): {' '.join(route_cmd)}")
                has_error = True

        if has_error:
            if not is_windows:
                logger.warning("[VPNConnector] ⚠️ 일부 라우팅 추가에 실패했습니다. '/etc/sudoers.d/openfortivpn' 권한을 검토해 주세요.")
            else:
                logger.warning("[VPNConnector] ⚠️ 일부 라우팅 추가에 실패했습니다. 이미 등록된 대역이거나 관리자 권한이 유실되었을 수 있습니다.")
