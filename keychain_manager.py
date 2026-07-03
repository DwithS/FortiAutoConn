import sys
import objc
import keyring
from LocalAuthentication import LAContext, LAPolicyDeviceOwnerAuthentication
from Foundation import NSRunLoop, NSDate
from logger import logger

class KeychainManager:
    @staticmethod
    def authenticate_touch_id(reason="VPN 연결을 위한 Touch ID 인증"):
        """
        macOS Touch ID 지문인식 또는 시스템 암호 인증을 트리거합니다.
        동기적으로 처리하기 위해 NSRunLoop를 사용하여 대기합니다.
        """
        context = LAContext.alloc().init()
        
        # 시스템 암호 대체 수단도 허용하는 정책 (LAPolicyDeviceOwnerAuthentication)
        policy = LAPolicyDeviceOwnerAuthentication
        
        # 지원 여부 확인
        can_evaluate, error = context.canEvaluatePolicy_error_(policy, None)
        if not can_evaluate:
            logger.error(f"[KeychainManager] 생체/비밀번호 인증을 사용할 수 없습니다: {error}")
            # Touch ID가 지원되지 않는 환경이라면(예: 클램쉘 모드 등에서 지문 센서 사용 불가 시)
            # 시스템 암호 입력 창이 뜨도록 처리되거나, 시스템 설정을 요구합니다.
            # 여기서는 명시적으로 False를 반환하되, 일반 비밀번호 수동 입력을 백업으로 고려할 수 있습니다.
            return False

        auth_result = {"success": False, "completed": False}

        def reply_handler(success, error):
            auth_result["success"] = success
            auth_result["completed"] = True
            if not success and error:
                logger.warning(f"[KeychainManager] 인증 실패: {error}")

        # 비동기 인증 호출
        context.evaluatePolicy_localizedReason_reply_(
            policy,
            reason,
            reply_handler
        )

        # 비동기 콜백이 실행 완료될 때까지 RunLoop를 돌며 동기 대기
        run_loop = NSRunLoop.currentRunLoop()
        while not auth_result["completed"]:
            run_loop.runMode_beforeDate_(
                "NSDefaultRunLoopMode",
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )

        return auth_result["success"]

    @staticmethod
    def get_password(service, username):
        """macOS 키체인에서 안전하게 암호를 가져옵니다."""
        try:
            return keyring.get_password(service, username)
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 조회 에러 ({service}/{username}): {e}")
            return None

    @staticmethod
    def save_password(service, username, password):
        """macOS 키체인에 암호를 안전하게 저장합니다."""
        try:
            keyring.set_password(service, username, password)
            return True
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 저장 에러 ({service}/{username}): {e}")
            return False

    @staticmethod
    def delete_password(service, username):
        """macOS 키체인에서 정보를 삭제합니다."""
        try:
            keyring.delete_password(service, username)
            return True
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 삭제 에러 ({service}/{username}): {e}")
            return False
