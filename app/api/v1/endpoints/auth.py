"""
인증 관련 API 엔드포인트
"""
from fastapi import APIRouter, HTTPException, status, Query
from datetime import datetime, timezone, timedelta
from app.models.schemas import (
    UserLogin, UserRegister, TokenResponse, 
    RefreshTokenRequest, RefreshTokenResponse, RegisterResponse
)
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.core.config import get_settings
import secrets
import jwt

router = APIRouter()

@router.post("/register", response_model=RegisterResponse)
async def register(user_data: UserRegister):
    """회원가입"""
    # 이미 존재하는 사용자인지 확인
    existing_user = AuthService.get_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 등록된 이메일입니다."
        )
    
    # 사용자 생성
    user = AuthService.create_user(user_data.email, user_data.password)
    
    # JWT 기반 인증 토큰 생성
    settings = get_settings()
    
    # 토큰 만료 시간 설정 (24시간)
    expiration = datetime.now(timezone.utc) + timedelta(hours=24)

    token_payload = {
        "email": user_data.email,
        "exp": expiration,
        "iat": datetime.now(timezone.utc),
        "type": "email_verification",
        "jti": secrets.token_urlsafe(32)  # JWT ID for uniqueness
    }

    verification_token = jwt.encode(
        token_payload,
        settings.secret_key,
        algorithm="HS256"
    )
    
    success = EmailService.send_verification_email(user_data.email, verification_token)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="이메일 전송에 실패했습니다."
        )
    
    return RegisterResponse(message=f"Verification email sent to {user_data.email}")


@router.post("/login", response_model=TokenResponse)
async def login(user_data: UserLogin):
    """로그인"""
    # 사용자 인증
    user = AuthService.authenticate_user(user_data.email, user_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 계정이 활성화되어 있는지 확인
    if not user.get('is_active'):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="계정이 활성화되지 않았습니다. 이메일 인증을 완료해주세요.",
        )
    
    # 토큰 생성
    access_token = AuthService.create_access_token(
        data={"sub": user['email'], "user_id": user['id']}
    )
    refresh_token = AuthService.create_refresh_token()
    
    # 리프레시 토큰 저장
    AuthService.store_refresh_token(user['email'], refresh_token)
    
    return TokenResponse(
        accessToken=access_token,
        refreshToken=refresh_token,
        expiresIn=3600  # 1시간
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(token_data: RefreshTokenRequest):
    """토큰 갱신"""
    # 리프레시 토큰 검증
    db_token = AuthService.verify_refresh_token(token_data.refreshToken)
    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 리프레시 토큰입니다.",
        )
    
    # 사용자 조회
    user = AuthService.get_user_by_email(db_token['user_email'])
    if not user or not user.get('is_active'):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없거나 비활성화된 계정입니다.",
        )
    
    # 새 액세스 토큰 생성
    access_token = AuthService.create_access_token(
        data={"sub": user['email'], "user_id": user['id']}
    )
    
    return RefreshTokenResponse(
        accessToken=access_token,
        expiresIn=3600  # 1시간
    )


@router.get("/verify")
async def verify_email(token: str = Query(...)):
    """이메일 인증"""
    try:
        settings = get_settings()
        
        # JWT 토큰 검증
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=["HS256"]
            )
            
            # 토큰 타입 확인
            if payload.get("type") != "email_verification":
                raise jwt.InvalidTokenError("잘못된 토큰 타입입니다.")
            
            email = payload.get("email")
            if not email:
                raise jwt.InvalidTokenError("토큰에 이메일 정보가 없습니다.")
                
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인증 토큰이 만료되었습니다. 새로운 인증 이메일을 요청해주세요."
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효하지 않은 인증 토큰입니다."
            )
        
        # 해당 이메일의 사용자 찾기
        user = AuthService.get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다."
            )
        
        # 이미 인증된 사용자인지 확인
        if user.get('is_verified'):
            return {
                "message": "이미 인증된 계정입니다.",
                "status": "already_verified"
            }
        
        # 사용자 인증 처리
        AuthService.activate_user(email)
        
        return {
            "message": f"{email} 계정의 이메일 인증이 완료되었습니다.",
            "status": "success"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="인증 처리 중 오류가 발생했습니다."
        )