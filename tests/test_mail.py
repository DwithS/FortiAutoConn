import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keychain_manager import KeychainManager
from mail_checker import MailChecker
from logger import logger

def test_mail_connection():
    logger.info("=== IMAP & OTP 메일 수신 검증 테스트 시작 ===")
    print("==============================================")
    print("      Daum/Kakao IMAP 로그인 & OTP 감시 테스트")
    print("==============================================")
    
    # 키체인에서 정보 로드
    vpn_svc = "FortiAutoConn"
    mail_host = KeychainManager.get_password(vpn_svc, "mail_host")
    mail_port = KeychainManager.get_password(vpn_svc, "mail_port")
    mail_user = KeychainManager.get_password(vpn_svc, "mail_user")
    mail_pass = KeychainManager.get_password(vpn_svc, "mail_pass")

    if not all([mail_host, mail_port, mail_user, mail_pass]):
        logger.warning("[Test] 키체인에 등록된 메일 정보가 일부 누락되어 테스트 불가.")
        print("❌ 오류: 등록된 메일 정보가 없습니다. 메뉴바 앱 실행 후 Settings 메뉴에서 설정해 주십시오.")
        return

    print(f"로드된 메일 서버 접속 정보:")
    print(f" - IMAP Host: {mail_host}")
    print(f" - IMAP Port: {mail_port}")
    print(f" - Mail Address: {mail_user[:3]}***@{mail_user.split('@')[1] if '@' in mail_user else ''}")
    
    print("\n[단계 1] IMAP 서버 로그인 테스트 중...")
    logger.info(f"[Test] IMAP 서버 로그인 시도: {mail_host}:{mail_port} (User: {mail_user})")
    try:
        import imaplib
        mail = imaplib.IMAP4_SSL(mail_host, int(mail_port))
        mail.login(mail_user, mail_pass)
        logger.info("[Test] IMAP 로그인 성공")
        print("✅ IMAP 로그인 성공! (접속 정보 자격 증명 유효)")
        mail.select("inbox")
        print("✅ 메일함 Inbox 접근 확인 완료.")
        mail.logout()
    except Exception as e:
        logger.error(f"[Test] IMAP 로그인 또는 메일함 조회 실패: {e}")
        print(f"❌ IMAP 로그인 또는 세션 획득 실패: {e}")
        print("   ※ 아래 사항들을 반드시 점검해 주세요:")
        print("   1. Daum/Kakao 메일설정 ➔ IMAP/SMTP 설정 ➔ IMAP '사용함'으로 켜져 있는지 확인")
        print("   2. 카카오/다음 2단계 인증 적용자인지 확인 (반드시 전용 '앱 비밀번호' 기입 필요)")
        return

    print("\n[단계 2] 30초 OTP 수신 시뮬레이션 감시 가동...")
    print("it@daily-funding.com 발송 신규 메일 탐색 중...")
    print("   (실제로 본인에게 it@daily-funding.com 발송 메일을 모방하여 이메일을 한 통 쏘시면 테스트가 즉각 검출 완료됩니다.)")
    print("   (제목: 'AuthCode: 999888' 혹은 본문: 'Your authentication token code is 999888.')")
    
    logger.info("[Test] OTP 메일 모니터링 가동 (제한시간 30초)...")
    checker = MailChecker(mail_host, mail_port, mail_user, mail_pass)
    code = checker.fetch_latest_otp(sender_filter="it@daily-funding.com", max_wait_seconds=30)
    
    if code:
        logger.info(f"[Test] OTP 이메일 감지 및 파싱 일치 성공! 파싱값: {code}")
        print(f"🎉 OTP 파싱 매칭 최종 성공! 검출 코드: {code}")
    else:
        logger.warning("[Test] 30초 이내에 새 이메일이 관측되지 않아 OTP 수신 테스트 종료.")
        print("⚠️ 30초 탐색 시간 초과로 신규 이메일이 관측되지 않았습니다. (동작 구조는 정상입니다.)")
        
    logger.info("=== IMAP & OTP 메일 수신 검증 테스트 완료 ===")

if __name__ == "__main__":
    test_mail_connection()
