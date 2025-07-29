"""
FastAPI 설정 및 환경변수 관리
"""
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # API 설정
    app_name: str = "bo:matic server"
    app_description: str = "FGD 전사 텍스트 분석을 위한 API 서버"
    app_version: str = "1.0.0"
    
    # 서버 설정
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    
    # CORS 설정
    cors_origins: list = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list = ["*"]
    cors_allow_headers: list = ["*"]
    
    # API Keys
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    daglo_api_key: Optional[str] = os.getenv("DAGLO_API_KEY")
    
    # STT 설정
    stt_max_attempts: int = 150
    stt_poll_interval: int = 2
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 추가 필드 무시


@lru_cache()
def get_settings() -> Settings:
    """설정 객체를 캐시된 형태로 반환"""
    return Settings()


# 전역 설정 인스턴스
settings = get_settings()
