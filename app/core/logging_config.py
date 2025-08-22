"""
로깅 설정
"""
import logging
import sys
from typing import Dict, Any


def setup_logging(log_level: str = "INFO") -> None:
    """애플리케이션 로깅을 설정합니다."""
    
    # 로그 레벨 설정
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # 로그 포맷 설정
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    
    # 기본 로깅 설정
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),  # Cloud Run용 표준 출력
        ],
        force=True  # 기존 설정 덮어쓰기
    )
    
    # 애플리케이션별 로거 설정
    app_loggers = {
        "app.services.openai_service": logging.DEBUG,
        "app.services.gemini_service": logging.DEBUG,
        "app.services.pipeline_service": logging.DEBUG,
        "app.utils.rate_limit_manager": logging.DEBUG,
        "app.services.stt_service": logging.INFO,
    }
    
    for logger_name, logger_level in app_loggers.items():
        logging.getLogger(logger_name).setLevel(logger_level)
    
    # 외부 라이브러리 로거 조정 (노이즈 감소)
    external_loggers = {
        "httpx": logging.WARNING,
        "urllib3": logging.WARNING,
        "google": logging.WARNING,
        "openai": logging.WARNING,
        "tenacity": logging.WARNING,
    }
    
    for logger_name, logger_level in external_loggers.items():
        logging.getLogger(logger_name).setLevel(logger_level)
    
    # 루트 로거에서 테스트 로그 출력
    root_logger = logging.getLogger()
    root_logger.info("Logging configuration completed successfully")


def get_logger(name: str) -> logging.Logger:
    """로거 인스턴스를 반환합니다."""
    return logging.getLogger(name)