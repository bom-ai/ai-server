"""
User Authentication 관련 서비스
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from jwt import PyJWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.core.config import get_settings
from app.models.database import User, RefreshToken
import secrets

settings = get_settings()

# 비밀번호 해시화 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthService:
    """인증 서비스 클래스"""
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """비밀번호 검증"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """비밀번호 해시화"""
        return pwd_context.hash(password)
    
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
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """이메일로 사용자 조회"""
        return db.query(User).filter(User.email == email).first()
    
    @staticmethod
    def create_user(db: Session, email: str, password: str) -> User:
        """사용자 생성"""
        hashed_password = AuthService.get_password_hash(password)
        db_user = User(
            email=email,
            hashed_password=hashed_password,
            is_active=False,  # 이메일 인증 후 활성화
            is_verified=False
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    
    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
        """사용자 인증"""
        user = AuthService.get_user_by_email(db, email)
        if not user:
            return None
        if not AuthService.verify_password(password, user.hashed_password):
            return None
        return user
    
    @staticmethod
    def store_refresh_token(db: Session, user_id: int, token: str) -> RefreshToken:
        """리프레시 토큰 저장"""
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        
        # 기존 토큰들을 모두 무효화
        db.query(RefreshToken).filter(RefreshToken.user_id == user_id).update(
            {"is_revoked": True}
        )
        
        db_token = RefreshToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at
        )
        db.add(db_token)
        db.commit()
        db.refresh(db_token)
        return db_token
    
    @staticmethod
    def verify_refresh_token(db: Session, token: str) -> Optional[RefreshToken]:
        """리프레시 토큰 검증"""
        db_token = db.query(RefreshToken).filter(
            RefreshToken.token == token,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc)
        ).first()
        return db_token
    
    @staticmethod
    def revoke_refresh_token(db: Session, token: str):
        """리프레시 토큰 무효화"""
        db.query(RefreshToken).filter(RefreshToken.token == token).update(
            {"is_revoked": True}
        )
        db.commit()
    
    @staticmethod
    def activate_user(db: Session, email: str):
        """사용자 계정 활성화"""
        user = AuthService.get_user_by_email(db, email)
        if user:
            user.is_active = True
            user.is_verified = True
            db.commit()
            db.refresh(user)
        return user


auth_service = AuthService()