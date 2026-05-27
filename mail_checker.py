import imaplib
import email
from email.utils import parsedate_to_datetime
import re
import datetime
import time
import base64

def encode_imap_utf7(s):
    """
    일반 유니코드 문자열을 IMAP RFC 3501 Modified UTF-7 문자열로 완벽하게 변환합니다.
    한글 메일함 폴더명(예: 'DF VPN 인증') 지원을 완벽하게 보장합니다.
    """
    if not s:
        return s
    
    # 영문/숫자/기본 특수문자만 있다면 변환 생략
    if all(32 <= ord(c) <= 126 for c in s):
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
    
    print(f"[MailChecker DEBUG] Direct IMAP socket send: {repr(cmd)}")
    
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

class MailChecker:
    def __init__(self, host, port, username, password, mailbox="INBOX"):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        
        # 💡 안전성 클렌징: 사용자가 실수로 따옴표를 포함해 입력한 경우 앞뒤 따옴표를 말끔하게 정리
        cleaned_mailbox = mailbox.strip().strip('"').strip("'").strip()
        
        # 한글 폴더명(비ASCII) 지원을 위해 IMAP Modified UTF-7 형식으로 자동 인코딩
        self.mailbox = encode_imap_utf7(cleaned_mailbox)


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
                
                # 🎯 자가 치유(Self-Healing) 폴더 매칭 시스템 구동 (바이트 다이렉트 바이패스 방식)
                status, folder_list = mail.list()
                target_folder_bytes = None
                
                if status == "OK" and folder_list:
                    for folder_info in folder_list:
                        # folder_info는 bytes 타입: b'(\\Noinferiors) "/" "DF VPN &EQsRdRGrEQwRcxG8-"'
                        
                        # 💡 바이트 단위로 정확히 쪼개서 유니코드 디코딩 노이즈 원천 격리
                        parts = folder_info.split(b' "/" ')
                        if len(parts) < 2:
                            parts = folder_info.split(b' "." ')
                            
                        if len(parts) >= 2:
                            # 서버가 전송해 준 원본 폴더 바이트명에서 양끝 따옴표 트리밍
                            folder_bytes = parts[-1].strip(b'"').strip(b"'").strip()
                            
                            # 비교 판별용으로만 디코딩 수행
                            folder_name_str = folder_bytes.decode('utf-8', errors='ignore')
                            target_clean = self.mailbox.strip('"').strip("'").strip()
                            
                            # 공통 핵심 키워드 매칭
                            target_keyword = "df vpn"
                            clean_target_lower = target_clean.lower().replace(" ", "")
                            clean_folder_lower = folder_name_str.lower().replace(" ", "")
                            key_no_space = target_keyword.replace(" ", "")
                            
                            if (key_no_space in clean_folder_lower) and (key_no_space in clean_target_lower):
                                is_match = True
                            else:
                                is_match = (target_clean.lower() in folder_name_str.lower()) or \
                                           (folder_name_str.lower() in target_clean.lower())
                            
                            if is_match:
                                # 매칭 성공: 유니코드가 아닌 깨끗한 서버 오리지널 'bytes' 자체를 보관!
                                target_folder_bytes = folder_bytes
                                print(f"[MailChecker] 🎯 사내 인증 메일함 지능형 바이트 매칭 성공! 서버 실제 바이트: {repr(folder_bytes)}")
                                break
                                
                # 매칭에 성공한 실제 폴더 바이트가 있다면 이를 사용하고, 실패 시 기존 값 활용
                if target_folder_bytes:
                    select_param = target_folder_bytes
                else:
                    select_param = self.mailbox
                
                # 💡 소켓 다이렉트 프레임 바이패스로 imaplib의 쿼팅 버그 원천 해결
                status, _ = direct_imap_select(mail, select_param)
                if status != "OK":
                    raise RuntimeError(f"메일함 {repr(select_param)} 선택 실패 (상태: {status})")


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
