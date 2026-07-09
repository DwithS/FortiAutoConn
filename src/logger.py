import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger():
    # 프로젝트 루트 경로 기준 logs 폴더 생성
    project_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(project_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    log_file = os.path.join(logs_dir, "fortiautoconn.log")
    
    logger = logging.getLogger("FortiAutoConn")
    
    # 중복 등록 방지
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # 시간, 레벨, 파일명/줄번호, 메시지 형식 지정
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s')
    
    # 1. 파일 핸들러 (회전 백업: 5MB씩 최대 5개 백업 유지)
    try:
        file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[Logger Setup Error] 로그 파일 핸들러 생성 실패: {e}")
        
    # 2. 콘솔 스트림 핸들러
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    logger.info("==========================================")
    logger.info("     FortiAutoConn 로깅 엔진 시작")
    logger.info("==========================================")
    
    return logger

# 전역에서 편하게 임포트하여 사용하는 로거 인스턴스
logger = setup_logger()
