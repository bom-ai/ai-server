"""
User Authentication 관련 서비스
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from jwt import PyJWTError
from fastapi import HTTPException, status
from app.core.config import get_settings
from app.models.datastore import user_entity, refresh_token_entity
import secrets
import bcrypt

settings = get_settings()


class AuthService:
    """인증 서비스 클래스"""
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """비밀번호 검증"""
        password_byte_enc = plain_password.encode('utf-8')
        
        # hashed_password가 문자열인 경우 bytes로 변환
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        
        return bcrypt.checkpw(password=password_byte_enc, hashed_password=hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """비밀번호 해시화"""
        pwd_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
        
        # 데이터베이스에 저장하기 위해 문자열로 변환하여 반환
        return hashed_password.decode('utf-8')
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """액세스 토큰 생성"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
        return encoded_jwt
    
    @staticmethod
    def create_refresh_token() -> str:
        """리프레시 토큰 생성"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def verify_token(token: str) -> dict:
        """토큰 검증"""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            email: str = payload.get("sub")
            if email is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return payload
        except PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    @staticmethod
    def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
        """이메일로 사용자 조회"""
        user = user_entity.get_user_by_email(email)
        return user  
    
    @staticmethod
    def create_user(email: str, password: str) -> Dict[str, Any]:
        """사용자 생성"""
        hashed_password = AuthService.get_password_hash(password)
        user = user_entity.create_user(email, hashed_password)
        return user  
    
    @staticmethod
    def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
        """사용자 인증"""
        user = AuthService.get_user_by_email(email)
        if not user:
            return None
        if not AuthService.verify_password(password, user['hashed_password']):
            return None
        return user
    
    @staticmethod
    def store_refresh_token(user_email: str, token: str) -> Dict[str, Any]:
        """리프레시 토큰 저장"""
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        token_entity = refresh_token_entity.store_refresh_token(user_email, token, expires_at)
        return token_entity  
    
    @staticmethod
    def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
        """리프레시 토큰 검증"""
        token_entity = refresh_token_entity.verify_refresh_token(token)
        return token_entity  
    
    @staticmethod
    def revoke_refresh_token(token: str):
        """리프레시 토큰 무효화"""
        refresh_token_entity.revoke_refresh_token(token)
    
    @staticmethod
    def activate_user(email: str) -> Optional[Dict[str, Any]]:
        """사용자 계정 활성화"""
        user = user_entity.activate_user(email)
        return user     


auth_service = AuthService()