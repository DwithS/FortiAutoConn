import sys
import keyring
from logger import logger

class KeychainManager:
    @staticmethod
    def authenticate_touch_id(reason="VPN 연결을 위한 Touch ID 인증"):
        """
        macOS Touch ID 또는 Windows Hello 인증을 트리거합니다.
        각 OS 환경에 맞춰 네이티브 인증을 동기적으로 대기 처리합니다.
        """
        if sys.platform == "darwin":
            return KeychainManager._authenticate_mac(reason)
        elif sys.platform == "win32":
            return KeychainManager._authenticate_windows(reason)
        else:
            logger.info(f"[KeychainManager] {sys.platform} 환경에서는 자격증명 인증을 건너뜁니다.")
            return True

    @staticmethod
    def _authenticate_mac(reason):
        """macOS Touch ID 지문인식 또는 시스템 암호 인증"""
        try:
            import objc
            from LocalAuthentication import LAContext, LAPolicyDeviceOwnerAuthentication
            from Foundation import NSRunLoop, NSDate
        except ImportError as e:
            logger.error(f"[KeychainManager] macOS 필수 라이브러리를 임포트할 수 없습니다: {e}")
            return False

        context = LAContext.alloc().init()
        policy = LAPolicyDeviceOwnerAuthentication
        
        can_evaluate, error = context.canEvaluatePolicy_error_(policy, None)
        if not can_evaluate:
            logger.error(f"[KeychainManager] 생체/비밀번호 인증을 사용할 수 없습니다: {error}")
            return False

        auth_result = {"success": False, "completed": False}

        def reply_handler(success, error):
            auth_result["success"] = success
            auth_result["completed"] = True
            if not success and error:
                logger.warning(f"[KeychainManager] 인증 실패: {error}")

        context.evaluatePolicy_localizedReason_reply_(
            policy,
            reason,
            reply_handler
        )

        run_loop = NSRunLoop.currentRunLoop()
        while not auth_result["completed"]:
            run_loop.runMode_beforeDate_(
                "NSDefaultRunLoopMode",
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )

        return auth_result["success"]

    @staticmethod
    def _authenticate_windows(reason):
        """Windows Hello (지문, 안면, PIN) 또는 시스템 계정 비밀번호 인증"""
        try:
            import asyncio
            from winsdk.windows.security.credentials.ui import UserConsentVerifier, UserConsentVerificationResult
        except ImportError:
            logger.error("[KeychainManager] Windows Hello를 위한 winsdk 라이브러리가 설치되어 있지 않습니다. pip install winsdk를 실행해 주세요.")
            return False

        async def verify():
            try:
                # API 사용 가능 여부 검사
                availability = await UserConsentVerifier.check_api_availability_async()
                # UserConsentVerifierAvailability.AVAILABLE = 0
                if availability != 0:
                    logger.warning(f"[KeychainManager] Windows Hello API 사용 불가능 (코드: {availability})")
                    return False

                # 인증 요청
                result = await UserConsentVerifier.request_verification_async(reason)
                # UserConsentVerificationResult.VERIFIED = 0
                return result == 0
            except Exception as e:
                logger.error(f"[KeychainManager] Windows Hello 요청 중 예외 발생: {e}")
                return False

        try:
            # asyncio 이벤트 루프가 이미 있는 경우와 없는 경우를 나눠 처리
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_running():
                # 이미 루프가 돌고 있다면 새로운 스레드에서 구동하거나 future를 동기 대기
                import threading
                result_holder = []
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    result_holder.append(new_loop.run_until_complete(verify()))
                    new_loop.close()
                t = threading.Thread(target=run_in_thread)
                t.start()
                t.join()
                return result_holder[0] if result_holder else False
            else:
                return loop.run_until_complete(verify())
        except Exception as e:
            logger.error(f"[KeychainManager] Windows Hello 동기 대기 에러: {e}")
            return False

    @staticmethod
    def get_password(service, username):
        """키체인/자격증명 관리자에서 안전하게 암호를 가져옵니다."""
        try:
            return keyring.get_password(service, username)
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 조회 에러 ({service}/{username}): {e}")
            return None

    @staticmethod
    def save_password(service, username, password):
        """키체인/자격증명 관리자에 암호를 안전하게 저장합니다."""
        try:
            keyring.set_password(service, username, password)
            return True
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 저장 에러 ({service}/{username}): {e}")
            return False

    @staticmethod
    def delete_password(service, username):
        """키체인/자격증명 관리자에서 정보를 삭제합니다."""
        try:
            keyring.delete_password(service, username)
            return True
        except Exception as e:
            logger.error(f"[KeychainManager] 키체인 삭제 에러 ({service}/{username}): {e}")
            return False
