import imaplib
import email
from email.utils import parsedate_to_datetime
import re
import datetime
import time
import base64
from logger import logger

def encode_imap_utf7(s):
    """
    일반 유니코드 문자열을 IMAP RFC 3501 Modified UTF-7 문자열로 완벽하게 변환합니다.
    한글 메일함 폴더명(예: 'DF VPN 인증') 지원을 완벽하게 보장합니다.
    """
    if not s:
        return s

    # 영문/숫자/기본 특수문자만 있다면 변환 생략
    # (단, '&'는 RFC 3501 Modified UTF-7에서 '&-'로 이스케이프해야 하므로 조기 반환 불가)
    if "&" not in s and all(32 <= ord(c) <= 126 for c in s):
        return s

    r = []
    in_b = []

    def flush_b():
        if in_b:
            b_str = "".join(in_b).encode("utf-16-be")
            b64 = base64.b64encode(b_str).decode("ascii").rstrip("=")
            r.append("&" + b64.replace("/", ",") + "-")
            in_b.clear()

    for c in s:
        ord_c = ord(c)
        if 32 <= ord_c <= 126:
            if c == "&":
                flush_b()
                r.append("&-")
            else:
                flush_b()
                r.append(c)
        else:
            in_b.append(c)

    flush_b()
    return "".join(r)

def direct_imap_select(mail, mailbox_name):
    """
    파이썬 imaplib의 쿼팅/인코딩 간섭 버그를 완전히 우회하여,
    IMAP 소켓에 직접 'TAG SELECT "폴더명"' 프레임을 쏘아 완벽한 진입을 보장합니다.
    """
    tag = mail._new_tag()  # tag는 bytes 타입 (예: b'IANB3')

    # 💡 imaplib 내부 상태에 태그 등록하여 KeyError 및 루프 엉킴 원천 방지
    mail.tagged_commands[tag] = None

    if isinstance(mailbox_name, bytes):
        mailbox_name = mailbox_name.decode('utf-8', errors='ignore')

    mailbox_name = mailbox_name.strip().strip('"').strip("'").strip()

    tag_str = tag.decode("ascii") if isinstance(tag, bytes) else tag

    # 완벽하게 규격화된 IMAP 프레임 직접 어셈블리
    cmd = f'{tag_str} SELECT "{mailbox_name}"\r\n'.encode('utf-8')

    logger.debug(f"[MailChecker DEBUG] Direct IMAP socket send: {repr(cmd)}")

    # 소켓 다이렉트 전송!
    mail.send(cmd)

    # 💡 imaplib 공식 완료 검증 메서드를 실행하여 내부 버퍼 수집 완료
    # 첫 번째 인자는 name='SELECT', 두 번째 인자는 tag(bytes)입니다.
    typ, dat = mail._command_complete('SELECT', tag)

    # 디코드 처리
    if isinstance(typ, bytes):
        typ = typ.decode('utf-8', errors='ignore')

    # mail.state를 SELECTED 상태로 명시 전환하여 imaplib 상태머신 만족시킴
    if typ == 'OK':
        mail.state = 'SELECTED'

    return typ, dat

# 이미 OTP 입력에 사용한 메일의 Message-ID 기록.
# 재연결 시 이전 시도에서 쓴(이미 만료된) 과거 OTP를 다시 집어 실패 루프를 도는 것을 방지합니다.
_consumed_message_ids = set()

# OTP 추출 정규식 (제목 또는 본문):
# 1) 제목: AuthCode: 123456
# 2) 본문: Your authentication token code is 123456.
OTP_CODE_PATTERN = re.compile(r"(?:AuthCode:\s*|Your authentication token code is\s*)(\d{6})", re.IGNORECASE)

class MailChecker:
    # 한 번의 OTP 감시 동안 허용되는 최대 IMAP 로그인 횟수 = 최대 폴링 횟수.
    # 예전에는 로그인 1회를 재사용하며 폴링했으나, 재사용 세션의 SELECT가 항상 소켓 타임아웃(8초)에
    # 걸려 OTP 1분 수명을 통째로 잡아먹는 문제가 확인되어(로그 분석), 폴링마다 새 연결로 로그인하도록
    # 되돌렸습니다. 대신 폴링 간격을 넓히고(POLL_INTERVAL_SECONDS) 이 횟수를 보수적으로 제한해
    # 계정 접근제한(과다 로그인 차단)을 피합니다. (OTP_TIMEOUT은 재시도 금지 사유라 폭주하지 않음)
    MAX_LOGIN_ATTEMPTS = 15

    # 메일 확인(폴링) 간격(초). 매 폴링마다 새 연결로 [로그인 → SELECT → SEARCH]를 수행합니다.
    POLL_INTERVAL_SECONDS = 4

    # 소켓 타임아웃(초)을 단계별로 분리합니다.
    # - CONNECT: TCP/TLS 핸드셰이크 + 로그인. 죽은(half-open) 연결을 오래 붙잡지 않도록 짧게.
    # - DATA: SELECT/SEARCH/FETCH. 다음/카카오 IMAP은 새 연결의 첫 SELECT/SEARCH 응답이
    #   8초를 넘길 때가 많은데(로그상 스톨이 항상 8초 천장에 붙음 = 우리가 응답을 끊는 중),
    #   이를 8초에서 끊고 재시도하면 폴링 3회(≈24초)를 낭비해 OTP 1분 수명을 깎아먹습니다.
    #   → 데이터 명령은 넉넉히 줘서 느린 서버 응답이 첫 폴링에 완료되게 합니다(폴링마다 새로
    #   로그인하므로 좀비 연결에 걸려도 그 1회 폴링만 손해입니다).
    CONNECT_TIMEOUT_SECONDS = 8
    DATA_TIMEOUT_SECONDS = 20

    # 이 시간(ms)을 넘긴 SELECT/SEARCH는 '서버 지연'으로 눈에 띄게 로그를 남겨, 어떤 명령이
    # 느린지 평상시 로그(디버그 비활성 상태)에서도 바로 진단할 수 있게 합니다.
    SLOW_OP_WARN_MS = 3000

    # FortiToken 인증 메일에 담긴 OTP 코드의 유효 수명(초). 발송 시점부터 이 시간이 지나면
    # 코드를 제출해도 게이트웨이가 무조건 거부합니다.
    OTP_VALIDITY_SECONDS = 60
    # OTP 제출 왕복(소켓 전송 + 게이트웨이 처리) 여유(초). '지금-메일발송시각'으로 계산한 코드 나이가
    # (유효 수명 - 이 여유)를 넘으면, 제출해도 만료로 실패할 가능성이 높으므로 사용하지 않고 더 최신
    # 메일을 기다립니다. (거의 만료된 코드 제출 → 실패 → 재시도 → 인증메일 남발의 악순환 차단)
    OTP_SUBMIT_MARGIN_SECONDS = 10

    # 인증(OTP) 메일 발신자 기본값. Settings에서 otp_sender로 변경 가능합니다.
    DEFAULT_OTP_SENDER = "it@daily-funding.com"

    def __init__(self, host, port, username, password, mailbox="INBOX", otp_sender=None):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.otp_sender = (otp_sender or self.DEFAULT_OTP_SENDER).strip()

        # 서버가 로그인을 명시적으로 '거부'(비밀번호 오류 등)했는지 여부.
        # True이면 상위(VPNConnector/App)에서 자동 재연결을 중단해 계정 잠금을 방지합니다.
        self.auth_failed = False

        # 💡 안전성 클렌징: 사용자가 실수로 따옴표를 포함해 입력한 경우 앞뒤 따옴표를 말끔하게 정리
        cleaned_mailbox = mailbox.strip().strip('"').strip("'").strip()

        # 한글 폴더명(비ASCII) 지원을 위해 IMAP Modified UTF-7 형식으로 자동 인코딩
        self.mailbox = encode_imap_utf7(cleaned_mailbox)

        # 서버의 실제 폴더 바이트명 캐시. list()로 1회만 해석하고 이후 폴링은 재사용합니다.
        # (폴링마다 새로 로그인하므로, list()까지 매번 반복하면 왕복이 늘고 SELECT 직전 상태를
        #  흔들 수 있어 최초 1회만 해석합니다.)
        self._resolved_folder = None

    def _connect_and_login(self):
        """
        IMAP SSL 접속 + 로그인을 수행합니다.
        네트워크 장애가 아닌 '서버의 명시적 로그인 거부'는 재시도해도 절대 성공할 수 없고,
        반복하면 메일 계정이 접근제한에 걸리므로 auth_failed 플래그를 세우고 즉시 예외를 전파합니다.
        """
        # 연결/로그인 단계는 짧은 타임아웃(CONNECT)으로 죽은 커넥션을 빨리 포기합니다.
        mail = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.CONNECT_TIMEOUT_SECONDS)
        try:
            mail.login(self.username, self.password)
        except imaplib.IMAP4.error:
            self.auth_failed = True
            try:
                mail.logout()
            except Exception:
                pass
            raise
        # 로그인 성공 후에는 데이터 명령(SELECT/SEARCH/FETCH)용으로 타임아웃을 넉넉히 넓힙니다.
        # (느린 서버가 8초를 넘겨 응답하려는 걸 잘라내 헛되이 재시도하는 문제 방지)
        try:
            mail.sock.settimeout(self.DATA_TIMEOUT_SECONDS)
        except Exception:
            pass
        return mail

    def verify_login(self):
        """
        VPN 비밀번호 제출(=인증 메일 발송 유발) 전에 메일 로그인이 유효한지 사전 점검합니다.
        메일 자격 증명이 깨진 상태로 VPN 인증을 반복하다 계정이 잠기는 사고를 원천 차단합니다.
        반환: True(로그인 유효 또는 일시적 네트워크 장애로 판별 불가) / False(서버가 로그인 거부).
        """
        self.auth_failed = False
        try:
            mail = self._connect_and_login()
            try:
                mail.logout()
            except Exception:
                pass
            logger.info("[MailChecker] 메일 로그인 사전 점검 통과.")
            return True
        except imaplib.IMAP4.error as e:
            logger.error(f"[MailChecker] 메일 로그인이 서버에서 거부되었습니다 (비밀번호/앱 비밀번호 확인 필요): {e}")
            return False
        except Exception as e:
            # 네트워크 등 일시 장애는 인증 실패로 단정하지 않고 본 감시 플로우에서 재판별
            logger.warning(f"[MailChecker] 메일 로그인 사전 점검 중 네트워크 오류 (통과 처리): {e}")
            return True

    def _resolve_target_folder(self, mail):
        """
        🎯 자가 치유(Self-Healing) 폴더 매칭: 서버의 실제 폴더 목록에서 목표 메일함을
        바이트 단위로 매칭합니다 (한글 폴더명 유니코드 디코딩 노이즈 원천 격리).
        매칭 실패 시 설정된 폴더명을 그대로 반환합니다.
        """
        try:
            status, folder_list = mail.list()
            if status != "OK" or not folder_list:
                return self.mailbox

            for folder_info in folder_list:
                # folder_info는 bytes 타입: b'(\\Noinferiors) "/" "DF VPN &EQsRdRGrEQwRcxG8-"'
                parts = folder_info.split(b' "/" ')
                if len(parts) < 2:
                    parts = folder_info.split(b' "." ')

                if len(parts) >= 2:
                    # 서버가 전송해 준 원본 폴더 바이트명에서 양끝 따옴표 트리밍
                    folder_bytes = parts[-1].strip(b'"').strip(b"'").strip()

                    # 비교 판별용으로만 디코딩 수행
                    folder_name_str = folder_bytes.decode('utf-8', errors='ignore')
                    target_clean = self.mailbox.strip('"').strip("'").strip()

                    # 핵심 키워드 매칭: 설정된 폴더명(UTF-7 인코딩 형태)의 ASCII 접두부를
                    # 키워드로 삼아, 서버가 비ASCII 부분을 다른 표기로 반환해도 매칭되게 합니다.
                    # (예: 'DF VPN &x3jJnQ-' → 접두부 'dfvpn')
                    ascii_prefix = target_clean.split("&", 1)[0].lower().replace(" ", "")
                    clean_folder_lower = folder_name_str.lower().replace(" ", "")

                    if len(ascii_prefix) >= 3 and ascii_prefix in clean_folder_lower:
                        is_match = True
                    else:
                        is_match = (target_clean.lower() in folder_name_str.lower()) or \
                                   (folder_name_str.lower() in target_clean.lower())

                    if is_match:
                        # 매칭 성공: 유니코드가 아닌 깨끗한 서버 오리지널 'bytes' 자체를 보관!
                        logger.info(f"[MailChecker] 🎯 사내 인증 메일함 지능형 바이트 매칭 성공! 서버 실제 바이트: {repr(folder_bytes)}")
                        return folder_bytes
        except Exception as e:
            logger.warning(f"[MailChecker] 폴더 목록 매칭 중 오류, 설정된 폴더명을 그대로 사용합니다: {e}")

        return self.mailbox

    def _scan_for_otp(self, mail, sender_filter, code_pattern, start_time):
        """선택된 메일함에서 신규 OTP 메일을 1회 스캔합니다. (연결/로그인 없음)

        OTP 코드는 발송 시점부터 OTP_VALIDITY_SECONDS(1분)만 유효하므로, '지금' 기준으로 계산한
        코드 나이가 유효 여유를 넘는 메일은 제출해도 실패하니 사용하지 않고 더 최신 메일을 기다립니다.
        """
        # 코드 나이 판정 기준 시각. 스캔 시작 시점으로 고정해 FETCH 왕복 동안의 오차를 줄입니다.
        now = datetime.datetime.now(datetime.timezone.utc)
        # 이 나이를 넘긴 코드는 제출해도 만료로 실패할 가능성이 높아 사용하지 않습니다.
        max_usable_age = self.OTP_VALIDITY_SECONDS - self.OTP_SUBMIT_MARGIN_SECONDS

        # 🚀 SEARCH 대상을 최근 메일로 한정해 서버측 스캔 비용을 줄입니다.
        # 인증 메일함에 누적된 과거 OTP 메일(로그상 sender 매칭 400건)을 서버가 폴링마다 전부
        # 스캔하느라 SEARCH가 9~16초씩 걸리던 것이 실측된 주 병목이었습니다. OTP는 발송 후
        # 60초만 유효하므로 오래된 메일을 볼 필요가 없어 SINCE로 최근 1일치만 검색합니다.
        # (서버 로컬 타임존/자정 경계로 당일치가 잘려나가는 것을 막기 위해 하루 여유를 둡니다.
        #  범위 안에 남는 과거 메일은 어차피 아래 코드 나이 필터가 걸러냅니다.)
        # 주의: strftime("%b")는 한국어 로케일에서 '7월'을 반환해 IMAP 날짜 포맷을 깨뜨리므로
        # 영문 월 약어를 직접 조립합니다.
        _MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        since = start_time - datetime.timedelta(days=1)
        since_date = f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}"

        # 진단: SEARCH 왕복 시간을 측정합니다. 좀비 커넥션이면 여기서 소켓 타임아웃까지
        # 블록되므로, 이 값이 8초에 근접하면 커넥션이 죽은 것으로 판단할 수 있습니다.
        t0 = time.monotonic()
        status, messages = mail.search(None, f'FROM "{sender_filter}" SINCE {since_date}')
        search_ms = (time.monotonic() - t0) * 1000
        matched = len(messages[0].split()) if (status == "OK" and messages and messages[0]) else 0
        # 느린 SEARCH는 평상시 로그에서도 보이도록 승격 (SELECT vs SEARCH 지연 원인 구분용)
        if search_ms > self.SLOW_OP_WARN_MS:
            logger.warning(f"[MailChecker] SEARCH 응답이 느립니다: {search_ms:.0f}ms, 매칭 {matched}건 (status={status})")
        else:
            logger.debug(f"[MailChecker] SEARCH 완료: {search_ms:.0f}ms, 매칭 {matched}건 (status={status})")
        if status != "OK" or not messages[0]:
            return None

        mail_ids = messages[0].split()
        # 가장 최근 메일부터 역순으로 탐색
        for mail_id in reversed(mail_ids):
            status, data = mail.fetch(mail_id, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # 메일 수신 일시 파싱
            date_str = msg.get("Date")
            if not date_str:
                continue

            mail_time = parsedate_to_datetime(date_str)
            # timezone-aware로 통일
            if mail_time.tzinfo is None:
                mail_time = mail_time.replace(tzinfo=datetime.timezone.utc)
            else:
                mail_time = mail_time.astimezone(datetime.timezone.utc)

            # OTP 코드의 '현재 나이'로 유효성 판정. 발송된 지 오래된 메일(이전 시도의 만료 코드나
            # 전송 지연으로 늦게 도착한 코드)은 제출해도 게이트웨이가 거부하므로 사용하지 않습니다.
            # (만료 OTP 제출 → 실패 → 재시도 → 인증 메일 남발로 이어지는 악순환 방지)
            code_age = (now - mail_time).total_seconds()
            if code_age > max_usable_age:
                # 최신순 탐색이므로 이 메일이 이미 만료(임박)면 더 과거 메일은 볼 필요 없이 중단.
                # 아직 이번 감시 시간이 남아 있다면 다음 폴링에서 더 최신 메일을 계속 기다립니다.
                logger.info(
                    f"[MailChecker] OTP 메일을 찾았으나 코드 나이({code_age:.0f}s)가 유효 한계"
                    f"({max_usable_age:.0f}s, 수명 {self.OTP_VALIDITY_SECONDS}s)를 넘어 사용하지 않고 "
                    f"더 최신 인증 메일을 기다립니다."
                )
                break

            # 이전 연결 시도에서 이미 사용한 OTP 메일은 건너뜀 (일회용 코드 재사용 금지)
            message_id = (msg.get("Message-ID") or "").strip()
            if message_id and message_id in _consumed_message_ids:
                continue

            # 제목 추출 및 디코딩
            subject = ""
            if msg.get("Subject"):
                subject_decoded = email.header.decode_header(msg.get("Subject"))
                for part, encoding in subject_decoded:
                    if isinstance(part, bytes):
                        subject += part.decode(encoding or "utf-8", errors="ignore")
                    else:
                        subject += part

            # 본문 추출
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
            else:
                payload = msg.get_payload(decode=True)
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

            # 제목 또는 본문에서 6자리 코드 탐색
            match = code_pattern.search(subject) or code_pattern.search(body)
            if match:
                otp_code = match.group(1)
                if message_id:
                    if len(_consumed_message_ids) > 200:
                        _consumed_message_ids.clear()
                    _consumed_message_ids.add(message_id)
                # 로그 파일이 평문으로 보관되므로 코드는 첫 자리만 남기고 마스킹
                masked = otp_code[:1] + "*" * (len(otp_code) - 1)
                logger.info(f"[MailChecker] OTP 메일 감지 성공! 추출된 OTP: {masked} (메일 시간: {mail_time})")
                return otp_code

        return None

    def fetch_latest_otp(self, sender_filter=None, max_wait_seconds=75):
        """
        메일함에서 최신 OTP 번호를 감시하여 반환합니다.
        sender_filter를 생략하면 설정된 otp_sender(기본 DEFAULT_OTP_SENDER)를 사용합니다.

        설계 (매 폴링마다 새로 로그인):
        - 예전에는 로그인 1회를 재사용하며 폴링했으나, 재사용 세션의 SELECT가 사실상 매번 소켓
          타임아웃(8초)에 걸려(로그로 확인됨) OTP의 1분 수명을 통째로 소진했습니다. 그래서 폴링마다
          [새 연결 → 로그인 → SELECT → SEARCH → 로그아웃]을 수행하도록 되돌렸습니다.
        - 대신 계정 접근제한(과다 로그인 차단)을 피하려고 폴링 간격을 넓히고(POLL_INTERVAL_SECONDS)
          전체 로그인 횟수를 MAX_LOGIN_ATTEMPTS로 제한합니다. (OTP 미도착은 REASON_OTP_TIMEOUT으로
          상위에서 재시도가 금지되므로 로그인이 연쇄 폭주하지 않습니다.)
        - 폴더 해석(list())은 최초 1회만 하고 서버 폴더 바이트를 캐시해 이후엔 SELECT만 반복합니다.
        - 코드 수명(1분)을 넘긴 메일은 _scan_for_otp가 제출 대상에서 제외합니다(만료 코드 제출 방지).
        - 서버가 로그인을 거부하면(비밀번호 오류) 즉시 중단하고 auth_failed=True를 세웁니다.
        """
        sender_filter = sender_filter or self.otp_sender
        logger.info(f"[MailChecker] {sender_filter} 로부터의 OTP 메일 감시 시작 "
                    f"(최대 {max_wait_seconds}초, 폴링마다 재로그인, 최대 {self.MAX_LOGIN_ATTEMPTS}회)...")

        self.auth_failed = False
        start_time = datetime.datetime.now(datetime.timezone.utc)
        elapsed = 0
        code_pattern = OTP_CODE_PATTERN
        login_attempts = 0

        while elapsed < max_wait_seconds:
            if login_attempts >= self.MAX_LOGIN_ATTEMPTS:
                logger.error(f"[MailChecker] IMAP 로그인 한도({self.MAX_LOGIN_ATTEMPTS}회) 초과. "
                             f"계정 보호를 위해 감시를 중단합니다.")
                return None
            login_attempts += 1

            mail = None
            op_start = time.monotonic()
            try:
                # 이번 폴링용 새 연결 + 로그인
                mail = self._connect_and_login()

                # 폴더 바이트는 최초 1회만 list()로 해석하고 이후 캐시 재사용
                if self._resolved_folder is None:
                    self._resolved_folder = self._resolve_target_folder(mail)
                select_param = self._resolved_folder

                sel_t0 = time.monotonic()
                status, _ = direct_imap_select(mail, select_param)
                select_ms = (time.monotonic() - sel_t0) * 1000
                # 느린 SELECT는 평상시 로그에서도 보이도록 승격 (SELECT vs SEARCH 지연 원인 구분용)
                if select_ms > self.SLOW_OP_WARN_MS:
                    logger.warning(f"[MailChecker] SELECT 응답이 느립니다: {select_ms:.0f}ms (status={status})")
                if status != "OK":
                    raise RuntimeError(f"메일함 {repr(select_param)} 선택 실패 (상태: {status})")

                otp_code = self._scan_for_otp(mail, sender_filter, code_pattern, start_time)
                logger.debug(f"[MailChecker] 폴링 완료: {(time.monotonic() - op_start) * 1000:.0f}ms "
                             f"(경과 {elapsed:.1f}s, 시도 {login_attempts}/{self.MAX_LOGIN_ATTEMPTS})")
                if otp_code:
                    return otp_code
            except imaplib.IMAP4.error as e:
                # 서버의 명시적 로그인 거부(비밀번호 오류 등)는 재시도해도 성공할 수 없고, 반복하면
                # 계정이 잠기므로 즉시 중단합니다. (_connect_and_login이 auth_failed를 이미 세팅)
                logger.error(f"[MailChecker] 메일 로그인 거부: {e}. 계정 접근제한 방지를 위해 재시도하지 않습니다.")
                return None
            except Exception as e:
                # 네트워크/좀비 커넥션 등 일시 오류는 이번 폴링만 버리고 다음 폴링에서 새로 로그인.
                blocked_ms = (time.monotonic() - op_start) * 1000
                logger.warning(f"[MailChecker] 이번 폴링 실패, 다음 폴링에서 재접속합니다 "
                               f"(블록 {blocked_ms:.0f}ms, 시도 {login_attempts}/{self.MAX_LOGIN_ATTEMPTS}): {e}")
            finally:
                if mail is not None:
                    try:
                        mail.logout()
                    except Exception:
                        pass

            # 폴링 간격 대기 후 새 연결로 다시 스캔
            time.sleep(self.POLL_INTERVAL_SECONDS)
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()

        logger.warning("[MailChecker] OTP 수신 대기 시간이 초과되었습니다.")
        return None
