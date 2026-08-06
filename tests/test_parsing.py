"""mail_checker의 순수 함수(네트워크/Touch ID 불필요) 단위 테스트.

이 프로젝트에서 가장 깨지기 쉬운 부분인 IMAP Modified UTF-7 인코딩,
OTP 정규식, 폴더 바이트 매칭, OTP 메일 스캔 필터링을 오프라인으로 검증합니다.

실행 방법 (둘 다 가능):
    python3 tests/test_parsing.py
    pytest tests/test_parsing.py
"""
import os
import sys
import datetime
import email.message
import email.utils

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mail_checker import (  # noqa: E402
    MailChecker,
    OTP_CODE_PATTERN,
    encode_imap_utf7,
    _consumed_message_ids,
)

SENDER = "it@daily-funding.com"


# ---------- IMAP Modified UTF-7 인코딩 ----------

def test_utf7_ascii_passthrough():
    assert encode_imap_utf7("INBOX") == "INBOX"
    assert encode_imap_utf7("") == ""


def test_utf7_korean_folder():
    # '인증' = U+C778 U+C99D → UTF-16BE C778C99D → b64 'x3jJnQ==' → 패딩 제거
    assert encode_imap_utf7("DF VPN 인증") == "DF VPN &x3jJnQ-"


def test_utf7_ampersand_escape():
    assert encode_imap_utf7("A&B") == "A&-B"


def test_utf7_slash_replaced_with_comma():
    # U+FFFF → b64 '//8' → RFC 3501은 '/' 대신 ',' 사용
    assert encode_imap_utf7("￿") == "&,,8-"


# ---------- OTP 정규식 ----------

def test_otp_pattern_subject_format():
    m = OTP_CODE_PATTERN.search("AuthCode: 123456")
    assert m and m.group(1) == "123456"


def test_otp_pattern_body_format():
    m = OTP_CODE_PATTERN.search("Your authentication token code is 654321.")
    assert m and m.group(1) == "654321"


def test_otp_pattern_case_insensitive():
    m = OTP_CODE_PATTERN.search("authcode:987654")
    assert m and m.group(1) == "987654"


def test_otp_pattern_rejects_short_code():
    assert OTP_CODE_PATTERN.search("AuthCode: 12345") is None


# ---------- OTP 메일 스캔 (가짜 IMAP 객체) ----------

def make_raw_mail(code, when, msg_id, sender=SENDER):
    m = email.message.EmailMessage()
    m["From"] = sender
    m["Subject"] = f"AuthCode: {code}"
    m["Date"] = email.utils.format_datetime(when)
    m["Message-ID"] = msg_id
    m.set_content(f"Your authentication token code is {code}.")
    return m.as_bytes()


class FakeIMAP:
    """_scan_for_otp이 사용하는 search/fetch만 흉내내는 최소 IMAP 대역."""

    def __init__(self, raw_messages):
        self.raw_messages = raw_messages
        self.last_query = None  # 마지막 SEARCH 쿼리 문자열 기록 (SINCE 필터 검증용)

    def search(self, charset, query):
        self.last_query = query
        if not self.raw_messages:
            return ("OK", [b""])
        ids = b" ".join(str(i + 1).encode() for i in range(len(self.raw_messages)))
        return ("OK", [ids])

    def fetch(self, mail_id, spec):
        idx = int(mail_id.decode() if isinstance(mail_id, bytes) else mail_id) - 1
        return ("OK", [(b"RFC822", self.raw_messages[idx])])


def _checker(mailbox="INBOX"):
    return MailChecker("imap.example.com", "993", "user", "pass", mailbox=mailbox)


def test_scan_returns_recent_code():
    _consumed_message_ids.clear()
    now = datetime.datetime.now(datetime.timezone.utc)
    fake = FakeIMAP([make_raw_mail("123456", now, "<fresh@test>")])
    assert _checker()._scan_for_otp(fake, SENDER, OTP_CODE_PATTERN, now) == "123456"


def test_scan_rejects_mail_older_than_60s():
    # 감시 시작보다 60초 이상 오래된 메일은 만료된 OTP일 수 있으므로 절대 사용하지 않음
    _consumed_message_ids.clear()
    now = datetime.datetime.now(datetime.timezone.utc)
    old = now - datetime.timedelta(seconds=120)
    fake = FakeIMAP([make_raw_mail("123456", old, "<stale@test>")])
    assert _checker()._scan_for_otp(fake, SENDER, OTP_CODE_PATTERN, now) is None


def test_scan_skips_already_consumed_message():
    # 같은 OTP 메일(Message-ID)은 재연결 시도에서 재사용 금지
    _consumed_message_ids.clear()
    now = datetime.datetime.now(datetime.timezone.utc)
    fake = FakeIMAP([make_raw_mail("123456", now, "<once@test>")])
    checker = _checker()
    assert checker._scan_for_otp(fake, SENDER, OTP_CODE_PATTERN, now) == "123456"
    assert checker._scan_for_otp(fake, SENDER, OTP_CODE_PATTERN, now) is None


def test_scan_search_query_limits_by_since_date_english_month():
    # SEARCH가 SINCE로 최근 메일만 조회하는지 + 날짜가 IMAP 규격(영문 월)인지 검증.
    # (strftime("%b")는 한국어 로케일에서 '7월'을 반환해 IMAP 날짜를 깨뜨리므로 회귀 방지)
    _consumed_message_ids.clear()
    # 결정적 검증을 위해 고정 시각(2026-07-27) 기준으로 하루 여유 → SINCE 26-Jul-2026 기대
    fixed = datetime.datetime(2026, 7, 27, 10, 0, 0, tzinfo=datetime.timezone.utc)
    fake = FakeIMAP([make_raw_mail("123456", fixed, "<since@test>")])
    _checker()._scan_for_otp(fake, SENDER, OTP_CODE_PATTERN, fixed)
    assert f'FROM "{SENDER}"' in fake.last_query
    assert "SINCE 26-Jul-2026" in fake.last_query


# ---------- 폴더 목록 바이트 매칭 ----------

class FakeIMAPList:
    def __init__(self, folder_lines):
        self.folder_lines = folder_lines

    def list(self):
        return ("OK", self.folder_lines)


def test_resolve_folder_exact_bytes_match():
    checker = _checker(mailbox="DF VPN 인증")
    fake = FakeIMAPList([b'(\\HasNoChildren) "/" "DF VPN &x3jJnQ-"'])
    assert checker._resolve_target_folder(fake) == b"DF VPN &x3jJnQ-"


def test_resolve_folder_ascii_prefix_keyword_match():
    # 서버가 비ASCII 부분을 다른 표기로 반환해도 ASCII 접두부('dfvpn')로 매칭
    checker = _checker(mailbox="DF VPN 인증")
    fake = FakeIMAPList([b'(\\HasNoChildren) "/" "DF VPN AUTH"'])
    assert checker._resolve_target_folder(fake) == b"DF VPN AUTH"


def test_resolve_folder_falls_back_to_configured_name():
    checker = _checker(mailbox="DF VPN 인증")
    fake = FakeIMAPList([b'(\\HasNoChildren) "/" "Sent"'])
    assert checker._resolve_target_folder(fake) == checker.mailbox


# ---------- OTP 발신자 설정 ----------

def test_otp_sender_default_and_override():
    assert _checker().otp_sender == MailChecker.DEFAULT_OTP_SENDER
    c = MailChecker("h", "993", "u", "p", otp_sender=" security@example.com ")
    assert c.otp_sender == "security@example.com"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
