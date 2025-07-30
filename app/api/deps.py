"""
API 의존성 정의
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.models.database import get_db, User
from app.services.auth_service import AuthService

security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """현재 인증된 사용자 가져오기"""
    try:
        # 토큰 검증
        payload = AuthService.verify_token(credentials.credentials)
        email = payload.get("sub")
        
        # 사용자 조회
        user = AuthService.get_user_by_email(db, email)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 활성화된 사용자인지 확인
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return user
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
from app.core.config import get_settings, Settings


def get_settings_dependency() -> Settings:
    """설정 의존성"""
    return get_settings()
