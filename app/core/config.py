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
    base_url: str = os.getenv("BASE_URL")
    
    # CORS 설정
    cors_origins: list = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list = ["*"]
    cors_allow_headers: list = ["*"]
    
    # API Keys
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    daglo_api_key: Optional[str] = os.getenv("DAGLO_API_KEY")
    
    # JWT 설정
    secret_key: str = os.getenv("SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60  # 1시간
    refresh_token_expire_days: int = 7     # 7일
    
    # Google Cloud 설정
    google_cloud_project: Optional[str] = os.getenv("GOOGLE_CLOUD_PROJECT")
    google_application_credentials: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    firestore_database: str = os.getenv("FIRESTORE_DATABASE")
    
    # 이메일 설정
    mail_server: Optional[str] = os.getenv("MAIL_SERVER")
    mail_port: int = int(os.getenv("MAIL_PORT", "587"))
    mail_username: Optional[str] = os.getenv("MAIL_USERNAME")
    mail_password: Optional[str] = os.getenv("MAIL_PASSWORD")
    mail_from: Optional[str] = os.getenv("MAIL_FROM")
    mail_use_tls: bool = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    
    # STT 설정
    stt_max_attempts: int = 150
    stt_poll_interval: int = 2
    
    # Google Cloud Storage 설정
    gcs_bucket_name: Optional[str] = os.getenv("GCS_BUCKET_NAME")
    
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
