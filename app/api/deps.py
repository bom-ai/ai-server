"""
API 의존성 관리
"""
from app.core.config import get_settings, Settings


def get_settings_dependency() -> Settings:
    """설정 의존성"""
    return get_settings()
