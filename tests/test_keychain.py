import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keychain_manager import KeychainManager

def test_keychain():
    print("==============================================")
    print("       macOS Touch ID & Keychain 연동 테스트")
    print("==============================================")
    
    # 1. 터치 ID 인증 작동성 테스트
    print("\n[단계 1] macOS Touch ID 인증 팝업 구동...")
    print("센서에 손가락을 접촉하거나 시스템 암호를 입력해 검증하세요.")
    success = KeychainManager.authenticate_touch_id("FortiAutoConn 키체인 연동 검증을 위해 인증해 주세요.")
    
    if not success:
        print("❌ Touch ID 인증 실패 또는 사용자에 의해 취소되었습니다.")
        return
    print("✅ Touch ID 본인 인증 통과 성공!")

    # 2. 키체인 읽기/쓰기 작동성 테스트
    print("\n[단계 2] Keychain 데이터 읽기/쓰기 검증...")
    test_svc = "FortiAutoConn_TestService"
    test_usr = "test_user_key"
    test_pwd = "dummy_secure_password_12345!"

    # 데이터 입력
    save_ok = KeychainManager.save_password(test_svc, test_usr, test_pwd)
    if save_ok:
        print("✅ Keychain 쓰기(저장) 성공")
    else:
        print("❌ Keychain 쓰기(저장) 실패")

    # 데이터 추출 비교
    loaded_pwd = KeychainManager.get_password(test_svc, test_usr)
    if loaded_pwd == test_pwd:
        print(f"✅ Keychain 복호화 로드 매칭 성공 (로드값: {loaded_pwd})")
    else:
        print(f"❌ Keychain 복호화 로드 실패 (가져온값: {loaded_pwd})")

    # 데이터 파기
    del_ok = KeychainManager.delete_password(test_svc, test_usr)
    if del_ok:
        print("✅ Keychain 테스트 더미 데이터 영구 정리 완료")
    else:
        print("❌ Keychain 테스트 더미 데이터 정리 실패")

if __name__ == "__main__":
    test_keychain()
