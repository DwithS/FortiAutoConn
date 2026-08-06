import threading
import pexpect
import time
import re
import subprocess
import ipaddress
from collections import deque
from logger import logger

class VPNConnector:
    STATUS_DISCONNECTED = "disconnected"
    STATUS_CONNECTING = "connecting"
    STATUS_CONNECTED = "connected"
    STATUS_FAILED = "failed"

    # 재시도해도 해결되지 않는 실패 원인 코드.
    # 이 값이 failure_reason에 세팅되면 App은 자동 재연결을 중단해 계정 접근제한(잠금)을 방지합니다.
    REASON_MAIL_AUTH = "mail_auth"   # 메일 로그인 거부 (비밀번호/앱 비밀번호 오류)
    REASON_VPN_AUTH = "vpn_auth"     # VPN 비밀번호 거부
    REASON_SUDO = "sudo"             # sudoers NOPASSWD 미설정 (setup.sh 재실행 필요)
    REASON_OTP = "otp"               # OTP 반복 거부
    REASON_OTP_TIMEOUT = "otp_timeout"  # 인증 메일이 제한 시간 내 미도착 (메일 지연)

    # OTP 인증 메일 대기 한도(초). FortiToken 메일 OTP 코드의 유효 수명은 발송 시점부터 약 1분이라,
    # 그 이후 도착한 코드는 제출해도 게이트웨이가 거부합니다. 따라서 대기를 무작정 길게 잡아도(예: 180초)
    # 만료된 코드를 붙잡고 있을 뿐이므로, 유효 수명에 제출 여유를 더한 현실적인 값으로 잡습니다.
    # 이 시간 내 유효한 코드가 도착하지 않으면 REASON_OTP_TIMEOUT으로 (재시도 없이) 중단합니다.
    OTP_WAIT_SECONDS = 75

    # 연결 수명 감시(health check) 설정.
    # 5초마다 ppp 인터페이스 상태를 확인하되, 순간적인 링크 흔들림(WiFi blip, pppd LCP
    # 재협상 등)을 실제 세션 유실로 오판하지 않도록 '연속' 실패 임계치를 둡니다. 한 번의
    # 실패로 즉시 전체 재접속(→ OTP 메일 재수신)에 들어가면, 순간 blip이 '수 분마다 끊김 +
    # 인증메일 폭탄'으로 증폭되는 악순환이 생기기 때문입니다. (정품 FortiClient은 keepalive로
    # 이런 blip을 흡수하지만 openfortivpn엔 자동 재접속이 없어 우리가 완충해 줘야 합니다.)
    HEALTHCHECK_INTERVAL_SECONDS = 5
    HEALTHCHECK_FAILURE_THRESHOLD = 3  # 연속 3회(≈15초) 실패해야 세션 유실로 확정

    def __init__(self, host, port, username, password, mail_checker, on_status_change=None, dns_bypass=False, split_tunnel=False, split_routes="", apply_routing_on_connect=True, exclude_interfaces=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail_checker = mail_checker
        self.on_status_change = on_status_change

        self.dns_bypass = dns_bypass
        self.split_tunnel = split_tunnel
        self.split_routes = split_routes

        # 🔀 make-before-break(무중단 세션 갱신) 지원용 옵션.
        # - apply_routing_on_connect=False: 연결 성공 시 스플릿 라우팅을 '아직' 붙이지 않습니다.
        #   기존 터널을 유지한 채 새 터널만 먼저 띄워두고(트래픽은 기존 터널로 계속 흐름),
        #   App 오케스트레이터가 새 터널 성공을 확인한 뒤에야 switch_routing_to_self()로
        #   라우팅을 원자적으로 새 인터페이스로 넘기기 위함입니다.
        # - exclude_interfaces: 이미 존재하는(기존 터널의) ppp 인터페이스 집합. 새 터널이
        #   자신의 인터페이스를 식별할 때 이 집합을 제외해 '새로 생긴' 인터페이스만 고릅니다.
        #   (그렇지 않으면 ifconfig 스캔이 기존 ppp0을 새 인터페이스로 오인함)
        self.apply_routing_on_connect = apply_routing_on_connect
        self._exclude_interfaces = set(exclude_interfaces or [])

        # 🛡️ 스플릿 터널링 시 회사 DNS 서버는 라우팅 대역 밖에 있어 도달 불가능한 경우가 대부분이며,
        # 그 상태로 DNS가 회사 서버로 덮어써지면 모든 도메인 해석이 실패해
        # '특정(사실상 모든) 인터넷 서비스가 안 되는' 증상이 발생합니다. → DNS 우회를 강제 동반 활성화.
        if self.split_tunnel and not self.dns_bypass:
            logger.info("[VPNConnector] 스플릿 터널링 활성 감지: 인터넷 끊김 방지를 위해 DNS 자동 변조 방지(우회)를 함께 활성화합니다.")
            self.dns_bypass = True

        self.status = self.STATUS_DISCONNECTED
        self.process = None
        self.thread = None
        self._stop_event = threading.Event()
        self.trusted_cert = None # 자동 감지된 게이트웨이 인증서 해시 저장용
        self.failure_reason = None
        self._active_ppp_if = None  # 연결 성공 시 확인된 실제 ppp 인터페이스명 (수명 감시에 재사용)
        self._mail_verified = False  # 메일 로그인 사전 점검 통과 여부 (자가 복구 재시도 시 중복 점검 방지)
        # 🔎 'Tunnel is up' 이후에는 expect 루프가 더 이상 프로세스 출력을 읽지 않아,
        # 세션 도중 pppd/openfortivpn이 왜 죽는지(LCP 실패, 게이트웨이 강제 종료 메시지 등)가
        # 로그에 전혀 남지 않던 진단 공백이 있었습니다. 수명 감시 루프에서 논블로킹으로
        # 계속 배수해 최근 출력을 여기 쌓아두고, 세션 유실 판정 시 함께 로그로 남깁니다.
        self._output_tail = deque(maxlen=100)

    def set_status(self, new_status):
        # 동일 상태 재통지 차단: 이미 DISCONNECTED로 통지된 커넥터를 정리 목적으로 stop()해도
        # App의 자동 재연결이 이중 스케줄링되지 않도록 상태가 실제로 바뀔 때만 콜백을 부릅니다.
        if new_status == self.status:
            return
        self.status = new_status
        if self.on_status_change:
            self.on_status_change(new_status)

    def start(self):
        """VPN 연결을 비동기 백그라운드 스레드로 시작합니다."""
        if self.status in [self.STATUS_CONNECTING, self.STATUS_CONNECTED]:
            logger.warning("[VPNConnector] 이미 연결 시도 중이거나 연결된 상태입니다.")
            return

        self._stop_event.clear()
        self.failure_reason = None
        self.set_status(self.STATUS_CONNECTING)
        self.thread = threading.Thread(target=self._run_vpn, daemon=True)
        self.thread.start()

    def stop(self, notify=True):
        """VPN 연결을 해제하고 프로세스를 정리합니다.

        notify=False: 상태 통지 없이 조용히 정리만 수행합니다. 자동 재연결 직전에
        기존(이미 FAILED/DISCONNECTED로 통지된) 커넥터를 교체·정리할 때 사용하며,
        이때 DISCONNECTED를 다시 통지하면 App의 재연결 플로우가 또 스케줄링됩니다.
        """
        logger.info("[VPNConnector] VPN 연결 종료 프로세스 작동...")
        self._stop_event.set()
        self._terminate_process()
        if notify:
            self.set_status(self.STATUS_DISCONNECTED)
        else:
            self.status = self.STATUS_DISCONNECTED

    def _terminate_process(self):
        """openfortivpn 프로세스만 조용히 종료합니다 (상태 통지 없음)."""
        if self.process:
            try:
                # pexpect child에 SIGTERM 전송
                self.process.terminate(force=True)
            except Exception as e:
                logger.error(f"[VPNConnector] openfortivpn 프로세스 해제 에러: {e}")

    def _fail(self, reason=None):
        """
        실패 처리 단일 경로: 프로세스를 정리한 뒤 FAILED 상태를 '한 번만' 통지합니다.
        (stop() 호출로 DISCONNECTED가 먼저 통지되면 App의 자동 재연결이 이중 스케줄링되어
         재시도 횟수가 두 배로 소진되고 알림이 중복 발생하는 문제가 있었음)
        """
        self.failure_reason = reason
        self._stop_event.set()
        self._terminate_process()
        self.set_status(self.STATUS_FAILED)

    def _run_vpn(self):
        # 0. 메일 로그인 사전 점검: VPN에 비밀번호를 제출하는 순간 서버가 인증 메일을 발송하므로,
        #    메일 자격 증명이 깨진 상태로 VPN 인증을 반복하면 [인증 메일 남발 + 메일 계정 접근제한]이
        #    동시에 발생합니다. VPN 인증을 시작하기 전에 여기서 원천 차단합니다.
        if not self._mail_verified:
            if not self.mail_checker.verify_login():
                logger.error("[VPNConnector] 메일 로그인 사전 점검 실패. 불필요한 인증 메일 발송을 막기 위해 VPN 인증을 시작하지 않습니다.")
                self._fail(self.REASON_MAIL_AUTH)
                return
            self._mail_verified = True

        # sudo -n: sudoers(NOPASSWD) 미설정 시 조용히 비밀번호 입력을 기다리다
        # 'Password:' 프롬프트에 VPN 비밀번호가 잘못 입력되는 사고를 막고 즉시 실패시킵니다.
        # 💡 argv 배열로 전달: 설정 UI에서 온 host/username 값에 공백 등이 섞여 있어도
        # 문자열 분해 과정에서 임의의 openfortivpn 인자로 해석되는 것(인자 주입)을 차단합니다.
        args = ["-n", "openfortivpn", f"{self.host}:{self.port}", "-u", str(self.username)]
        if self.trusted_cert:
            # 이미 자동 감지된 인증서 해시가 있다면 실행 인자에 포함하여 검증 에러 우회
            args += ["--trusted-cert", self.trusted_cert]
        if self.dns_bypass:
            args += ["--pppd-no-peerdns", "--no-dns"]
        if self.split_tunnel:
            args.append("--no-routes")
        logger.info(f"[VPNConnector] openfortivpn 실행 명령: sudo {' '.join(args)}")

        # 반복 제출 방지 카운터: 거부된 비밀번호/OTP를 계속 다시 보내면
        # 인증 메일이 남발되고 VPN 계정이 잠기므로 횟수를 엄격히 제한합니다.
        password_prompts = 0
        otp_prompts = 0

        try:
            # pexpect를 사용한 터미널 프롬프트 실시간 제어
            # 인코딩 utf-8 설정 필수
            self.process = pexpect.spawn("sudo", args, encoding='utf-8', timeout=120)

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
                    password_prompts += 1
                    if password_prompts > 1:
                        # 같은 비밀번호가 거부된 뒤 재요구된 상황 → 반복 제출은 계정 잠금을 유발하므로 즉시 중단
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
                    # 1차 비밀번호 제출 후 다음/카카오 이메일로 발송된 최신 메일 OTP 조회
                    otp_code = self.mail_checker.fetch_latest_otp(max_wait_seconds=self.OTP_WAIT_SECONDS)
                    if otp_code:
                        # 로그 파일이 평문으로 보관되므로 코드는 첫 자리만 남기고 마스킹
                        masked = otp_code[:1] + "*" * (len(otp_code) - 1)
                        logger.info(f"[VPNConnector] 메일에서 파싱된 OTP 적용 입력: {masked}")
                        self.process.sendline(otp_code)
                    else:
                        # 원인 분기:
                        # - 메일 로그인 거부(auth_failed): 비밀번호 문제 → REASON_MAIL_AUTH
                        # - 그 외(로그인은 됐으나 제한 시간 내 메일 미도착): 메일 지연 → REASON_OTP_TIMEOUT
                        #   이때 자동 재시도하면 VPN 비밀번호를 다시 제출해 새 인증메일이 또 발송되고,
                        #   이미 느린 메일함을 더 붐비게 만드는 악순환이 되므로 재시도하지 않는 사유로 분류합니다.
                        if getattr(self.mail_checker, "auth_failed", False):
                            reason = self.REASON_MAIL_AUTH
                        else:
                            reason = self.REASON_OTP_TIMEOUT
                        logger.warning(f"[VPNConnector] 메일 수신 실패 또는 OTP 파싱 타임아웃(사유: {reason}). VPN 연결을 취소합니다.")
                        self._fail(reason)
                        return

                elif index == 2:
                    logger.info("[VPNConnector] 신뢰되지 않는 게이트웨이 인증서 경고 감지. 'y' 전송하여 자동 신뢰 허용...")
                    self.process.sendline("y")

                elif index == 3:
                    logger.info("[VPNConnector] VPN 터널 연결 성공! (Tunnel is up and running)")
                    # 이후 수명 감시(health check)에서도 재사용할 실제 ppp 인터페이스를 여기서 한 번만 확인
                    self._active_ppp_if = self._get_active_ppp_interface()
                    # make-before-break 갱신용 대기 커넥터는 라우팅을 여기서 붙이지 않습니다.
                    # (기존 터널이 라우팅을 쥐고 있어야 전환 전까지 무중단이 유지됨)
                    if self.split_tunnel and self.apply_routing_on_connect:
                        self._apply_split_routing(self._active_ppp_if)
                    self.set_status(self.STATUS_CONNECTED)
                    break

                elif index == 4:
                    output = self.process.before or ""
                    logger.error(f"[VPNConnector] openfortivpn 프로세스가 초기 연결 중 예기치 않게 종료되었습니다.\n로그: {output}")

                    # sudoers NOPASSWD 미설정 감지 (sudo -n이 즉시 거부한 경우)
                    if "sudo:" in output and ("password is required" in output or "암호가 필요" in output):
                        logger.error("[VPNConnector] sudo 무암호 권한이 설정되어 있지 않습니다. ./setup.sh 를 다시 실행해 주세요.")
                        self._fail(self.REASON_SUDO)
                        return

                    # 💡 핵심 자가 복구: 신뢰할 수 없는 사내 인증서 에러 감지 시 sha256 해시를 추출하여 자동 우회 재시도
                    if "Gateway certificate validation failed" in output or "trusted-cert" in output:
                        cert_match = re.search(r"(?:trusted-cert\s*=\s*|--trusted-cert\s+)([0-9a-fA-F]{64})", output)
                        if not cert_match:
                            cert_match = re.search(r"sha256 digest:\s*([0-9a-fA-F]{64})", output)

                        if cert_match:
                            detected_hash = cert_match.group(1)
                            # 중복 무한 재시도를 방지하기 위해 새로운 해시 감지 시에만 자동 갱신 및 재접속 구동
                            if detected_hash != self.trusted_cert:
                                logger.info(f"[VPNConnector] 🛡️ 신뢰되지 않는 사내 게이트웨이 인증서 해시 자동 검출: {detected_hash}")
                                logger.info("[VPNConnector] 해당 인증서를 화이트리스트에 임시 자동 추가하여 1초 후 안전 재접속을 구동합니다...")
                                self.trusted_cert = detected_hash
                                self.process.close()
                                # 대기 중 사용자가 Disconnect(stop)를 누르면 재시도 없이 즉시 중단
                                if self._stop_event.wait(1):
                                    return
                                # 새로운 스레드로 무중단 자가 복구 연결 수행
                                threading.Thread(target=self._run_vpn, daemon=True).start()
                                return

                    # 인증 실패로 종료된 경우는 재시도 금지 (반복 시 계정 잠금)
                    if "Could not authenticate" in output or "Authentication failed" in output:
                        self._fail(self.REASON_VPN_AUTH)
                        return

                    self._fail()
                    return

                elif index == 5:
                    # 주기적인 루프 감시
                    pass

            # VPN 연결이 수립(STATUS_CONNECTED)된 후 연결 수명 감시 루프
            #
            # 💡 핵심 버그 수정: self.process는 pexpect가 감시하는 'sudo openfortivpn' 래퍼 프로세스인데,
            # 실제 터널을 담당하는 openfortivpn/pppd 자식 프로세스가 죽어도(세션 만료 등) sudo 래퍼 자체는
            # 자식을 회수(reap)하지 못한 채(좀비) 계속 살아있을 수 있습니다. 이 경우 isalive()만 보면
            # 터널이 실제로는 끊겼는데도 영원히 '연결됨(🟢)'으로 오판하게 됩니다.
            # → 자식 프로세스 생존 여부와 별개로, 실제 ppp 인터페이스가 UP/RUNNING 상태인지도 함께 확인합니다.
            consecutive_failures = 0
            while not self._stop_event.is_set():
                self._drain_process_output()
                process_alive = self.process.isalive()
                tunnel_up, probe_detail = self._probe_ppp_interface(self._active_ppp_if)

                if process_alive and tunnel_up:
                    # 정상 폴링: 이전에 쌓인 순간 실패 카운트를 리셋(blip 흡수)
                    if consecutive_failures:
                        logger.info(
                            f"[VPNConnector] ppp 인터페이스({self._active_ppp_if}) 상태가 회복되어 "
                            f"세션 유실 판정을 취소합니다 (직전 연속 실패 {consecutive_failures}회)."
                        )
                    consecutive_failures = 0
                else:
                    # 실패 폴링: 즉시 끊지 않고 연속 실패를 누적. 순간 blip이면 다음 폴링에서 회복됨.
                    consecutive_failures += 1
                    logger.warning(
                        f"[VPNConnector] 연결 수명 감시 실패 감지 "
                        f"({consecutive_failures}/{self.HEALTHCHECK_FAILURE_THRESHOLD}회 연속) — "
                        f"프로세스 생존: {process_alive}, ppp 인터페이스({self._active_ppp_if}): {probe_detail}"
                    )
                    if consecutive_failures >= self.HEALTHCHECK_FAILURE_THRESHOLD:
                        self._drain_process_output()  # 판정 직전 마지막 출력까지 한 번 더 배수
                        tail_log = "\n".join(self._output_tail) if self._output_tail else "(캡처된 출력 없음 — 조용히 종료됨)"
                        logger.warning(
                            f"[VPNConnector] VPN 터널 세션이 유실되었습니다 "
                            f"(연속 {consecutive_failures}회 실패, 프로세스 생존: {process_alive}, "
                            f"ppp 인터페이스({self._active_ppp_if}): {probe_detail}).\n"
                            f"세션 종료 전후 openfortivpn/pppd 출력(최근 {len(self._output_tail)}줄):\n{tail_log}"
                        )
                        self.set_status(self.STATUS_DISCONNECTED)
                        break

                # 일정 간격으로 연결 활성화 지속 모니터링
                # (stop() 요청 시 즉시 깨어나도록 sleep 대신 이벤트 대기 사용)
                self._stop_event.wait(self.HEALTHCHECK_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f"[VPNConnector] VPN 구동 스레드 내부 오류: {e}")
            self._fail()

    def _drain_process_output(self):
        """'Tunnel is up' 이후 pexpect가 더 이상 읽지 않는 프로세스 출력을 논블로킹으로 배수해
        self._output_tail에 최근 줄만 남깁니다. openfortivpn/pppd가 세션 도중 남기는 종료 사유
        (LCP 재협상 실패, 게이트웨이의 연결 종료 메시지 등)를 세션 유실 판정 시 함께 로그로
        남기기 위한 것으로, 정상 상태에서도 매 폴링마다 조용히 호출됩니다."""
        if not self.process:
            return
        try:
            while True:
                chunk = self.process.read_nonblocking(size=4096, timeout=0)
                if not chunk:
                    break
                for line in chunk.splitlines():
                    line = line.strip()
                    if line:
                        self._output_tail.append(line)
        except pexpect.TIMEOUT:
            pass  # 새로 읽을 출력 없음 (정상)
        except pexpect.EOF:
            pass  # 프로세스 종료로 출력 스트림이 닫힘
        except Exception as e:
            logger.debug(f"[VPNConnector] 프로세스 출력 배수 중 에러(무시 가능): {e}")

    @staticmethod
    def list_active_ppp_interfaces():
        """현재 UP/RUNNING 상태인 ppp 인터페이스 집합을 돌려줍니다.
        make-before-break 갱신 직전에 '기존 인터페이스' 스냅샷을 떠서, 새 터널이
        생성한 인터페이스만 골라낼 때 제외 집합으로 사용합니다."""
        try:
            res = subprocess.check_output(["ifconfig"], encoding="utf-8")
            return set(re.findall(r"(ppp\d+): flags=.*<UP,POINTOPOINT,RUNNING", res))
        except Exception as e:
            logger.error(f"[VPNConnector] ppp 인터페이스 목록 조회 중 에러: {e}")
            return set()

    def _get_active_ppp_interface(self, wait_seconds=10):
        """
        활성 ppp 인터페이스를 탐색합니다.
        'Tunnel is up' 로그 직후에는 인터페이스가 아직 뜨는 중일 수 있으므로
        잠시 재시도하며 대기합니다 (잘못된 인터페이스에 라우팅이 등록되는 것을 방지).

        make-before-break 대기 커넥터는 self._exclude_interfaces(기존 터널 인터페이스)를
        제외하고 '새로 생긴' 인터페이스만 고릅니다. 기존 인터페이스가 제외 집합에 있는데
        새 인터페이스를 끝내 못 찾으면 None을 돌려주어(잘못된 ppp0 폴백 금지) 호출측이
        전환을 취소하고 기존 터널을 유지하도록 합니다.
        """
        deadline = time.time() + wait_seconds
        while True:
            try:
                res = subprocess.check_output(["ifconfig"], encoding="utf-8")
                # ppp 인터페이스 중 UP, RUNNING 상태 스캔
                interfaces = re.findall(r"(ppp\d+): flags=.*<UP,POINTOPOINT,RUNNING", res)
                # 기존 터널 인터페이스는 제외하고 새로 생성된 것만 후보로
                candidates = [i for i in interfaces if i not in self._exclude_interfaces]
                if candidates:
                    return candidates[0]
            except Exception as e:
                logger.error(f"[VPNConnector] ppp 인터페이스 탐색 중 에러: {e}")

            if time.time() >= deadline:
                if self._exclude_interfaces:
                    # 새 터널의 인터페이스를 식별하지 못함 → 라우팅 전환 불가. 호출측이 실패 처리.
                    logger.warning("[VPNConnector] 새 ppp 인터페이스를 찾지 못했습니다(기존 제외). 라우팅 전환을 진행할 수 없습니다.")
                    return None
                logger.warning("[VPNConnector] 활성 ppp 인터페이스를 찾지 못해 기본값 ppp0을 사용합니다.")
                return "ppp0"  # 기본값 백업
            time.sleep(0.5)

    def _probe_ppp_interface(self, ifname):
        """
        지정된 ppp 인터페이스가 여전히 UP/RUNNING 상태인지 확인하고 (정상여부, 사유) 를 돌려줍니다.
        openfortivpn/pppd 자식 프로세스가 죽으면 이 인터페이스도 함께 사라지므로,
        pexpect가 감시하는 'sudo' 래퍼 프로세스의 생존 여부만으로는 잡아낼 수 없는
        '자식만 죽고 부모(sudo)는 좀비 상태로 살아있는' 상황을 탐지하는 용도입니다.

        반환하는 사유 문자열은 세션 유실의 진짜 원인(인터페이스 소멸 vs 플래그 순간 변화 vs
        진단 명령 오류)을 로그로 구분하기 위한 것입니다. 이걸로 '실제 링크가 죽는지' vs
        '헬스체크가 순간 헛디디는지'를 사후에 판별할 수 있습니다.
        """
        if not ifname:
            return False, "인터페이스명 미확정(None)"
        try:
            res = subprocess.check_output(["ifconfig", ifname], encoding="utf-8", stderr=subprocess.DEVNULL)
            flags_match = re.search(r"flags=\S*<([^>]*)>", res)
            flags = flags_match.group(1) if flags_match else "flags 파싱 실패"
            if re.search(r"flags=.*<UP,POINTOPOINT,RUNNING", res):
                return True, f"정상(flags={flags})"
            # 인터페이스는 존재하나 UP/POINTOPOINT/RUNNING 조합이 아님 → 순간 플래그 변화 가능성
            return False, f"인터페이스 존재하나 RUNNING 아님(flags={flags})"
        except subprocess.CalledProcessError:
            # ifconfig가 비정상 종료 → 인터페이스 자체가 더 이상 존재하지 않음 (터널 소멸)
            return False, "인터페이스 소멸(ifconfig 조회 실패)"
        except Exception as e:
            logger.error(f"[VPNConnector] ppp 인터페이스({ifname}) 상태 확인 중 에러: {e}")
            # 확인 자체가 실패한 경우는 네트워크 명령어 문제일 수 있으므로 오탐(불필요한 재연결)을 피하기 위해 생존으로 간주
            return True, f"진단 명령 오류로 생존 간주({e})"

    def switch_routing_to_self(self):
        """make-before-break: 스플릿 라우팅을 이 커넥터(새 터널)의 인터페이스로 원자적으로 재지정합니다.
        기존 터널이 쥐고 있던 라우팅을 route change로 넘겨받은 뒤에야 기존 터널을 정리하므로
        전환 시점의 트래픽 공백이 사실상 없습니다. 인터페이스가 확정되지 않았으면 False를 돌려줍니다."""
        if not self._active_ppp_if:
            logger.warning("[VPNConnector] 새 터널 인터페이스가 확정되지 않아 라우팅 전환을 진행할 수 없습니다.")
            return False
        self._apply_split_routing(self._active_ppp_if, switch=True)
        return True

    def _apply_split_routing(self, ppp_if=None, switch=False):
        if not self.split_routes:
            logger.info("[VPNConnector] 스플릿 라우팅 대역이 비어 있어 등록을 생략합니다.")
            return

        if not ppp_if:
            ppp_if = self._get_active_ppp_interface()
        routes = [r.strip() for r in self.split_routes.split(",") if r.strip()]

        action = "전환(change)" if switch else "등록(add)"
        logger.info(f"[VPNConnector] 🛠️ 스플릿 터널링 라우팅 {action}: 인터페이스 {ppp_if} 기준으로 처리합니다...")

        has_error = False
        for route in routes:
            # 잘못된 형식의 대역이 route 명령에 들어가 라우팅 테이블이 오염되는 것을 방지
            try:
                ipaddress.ip_network(route, strict=False)
            except ValueError:
                logger.warning(f"[VPNConnector] ⚠️ 잘못된 IP 대역 형식이라 건너뜁니다: {route!r} (올바른 예: 10.0.0.0/8)")
                has_error = True
                continue

            if switch:
                # 기존 인터페이스로 향하던 라우팅을 새 인터페이스로 원자적 재지정.
                # 해당 대역이 아직 라우팅 테이블에 없으면 change가 실패하므로 add로 폴백합니다.
                change_cmd = ["sudo", "-n", "route", "change", "-net", route, "-interface", ppp_if]
                logger.info(f"[VPNConnector] 라우팅 전환 시도: {' '.join(change_cmd)}")
                ret = subprocess.call(change_cmd)
                if ret != 0:
                    add_cmd = ["sudo", "-n", "route", "add", "-net", route, "-interface", ppp_if]
                    logger.info(f"[VPNConnector] change 실패 → add 폴백: {' '.join(add_cmd)}")
                    ret = subprocess.call(add_cmd)
            else:
                route_cmd = ["sudo", "-n", "route", "add", "-net", route, "-interface", ppp_if]
                logger.info(f"[VPNConnector] 라우팅 테이블 등록 시도: {' '.join(route_cmd)}")
                ret = subprocess.call(route_cmd)

            if ret != 0:
                logger.warning(f"[VPNConnector] ⚠️ 라우팅 {action} 실패(반환 코드 {ret}): {route} → {ppp_if}")
                has_error = True

        if has_error:
            logger.warning("[VPNConnector] ⚠️ 일부 라우팅 처리에 실패했습니다. '/etc/sudoers.d/openfortivpn' 권한이 갱신되지 않았거나 (/sbin/route NOPASSWD 미등록), 이미 등록된 대역일 수 있습니다.")
