import imaplib
import email
from email.utils import parsedate_to_datetime
import re
import datetime
import time

class MailChecker:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password

    def fetch_latest_otp(self, sender_filter="it@daily-funding.com", max_wait_seconds=90):
        """
        메일함에서 최신 OTP 번호를 감시하여 반환합니다.
        max_wait_seconds 동안 최근 2분 이내에 수신된 인증메일을 탐색합니다.
        """
        print(f"[MailChecker] {sender_filter} 로부터의 OTP 메일 감시 시작 (최대 {max_wait_seconds}초 대기)...")
        
        start_time = datetime.datetime.now(datetime.timezone.utc)
        elapsed = 0
        
        # 메일 제목 또는 본문 정규식 패턴
        # 1) 제목: AuthCode: 123456
        # 2) 본문: Your authentication token code is 123456.
        code_pattern = re.compile(r"(?:AuthCode:\s*|Your authentication token code is\s*)(\d{6})", re.IGNORECASE)

        while elapsed < max_wait_seconds:
            try:
                # SSL IMAP 연결
                mail = imaplib.IMAP4_SSL(self.host, self.port)
                mail.login(self.username, self.password)
                mail.select("inbox")

                # sender_filter를 기준으로 메일 검색 (FROM 검색)
                status, messages = mail.search(None, f'FROM "{sender_filter}"')
                
                if status == "OK" and messages[0]:
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
                        
                        # 감시를 시작하기 최대 2분 전부터 수신된 메일까지만 검색 범위로 인정
                        time_diff = (start_time - mail_time).total_seconds()
                        if time_diff > 180:  # 3분(넉넉히) 이전 메일은 패스
                            # 역순이므로 이 시점부터 과거 메일은 탐색 중단
                            break
                        
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
                            print(f"[MailChecker] OTP 메일 감지 성공! 추출된 OTP: {otp_code} (메일 시간: {mail_time})")
                            mail.logout()
                            return otp_code

                mail.logout()
            except Exception as e:
                print(f"[MailChecker] 메일 확인 루프 에러: {e}")
            
            # 3초 대기 후 다시 시도
            time.sleep(3)
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
        
        print("[MailChecker] OTP 수신 대기 시간이 초과되었습니다.")
        return None
