"""
Pydantic 모델 정의
"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class STTRequest(BaseModel):
    """STT 요청 모델"""
    audio_url: str                      # 음성 파일 URL
    language: str = "ko"                # 언어 설정
    enable_speaker_diarization: bool    # 화자 분리 기능


class AnalysisRequest(BaseModel):
    """텍스트 분석 요청 모델"""
    text_content: str                   # 분석할 텍스트
    custom_items: Optional[List[str]] = None  # 커스텀 분석 항목 리스트


class PipelineRequest(BaseModel):
    """전체 파이프라인 요청 모델"""
    audio_url: str                      # 음성 파일 URL
    language: str = "ko"                # 언어 설정
    enable_speaker_diarization: bool = True  # 화자 분리 기능
    custom_items: Optional[List[str]] = None  # 커스텀 분석 항목 리스트


class STTResponse(BaseModel):
    """STT 응답 모델"""
    status: str
    message: str
    rid: Optional[str] = None
    transcribed_text: Optional[str] = None


class AnalysisResponse(BaseModel):
    """텍스트 분석 응답 모델"""
    status: str
    message: str
    result: Optional[str] = None


class PipelineResponse(BaseModel):
    """전체 파이프라인 응답 모델"""
    status: str
    message: str
    stt_rid: Optional[str] = None
    transcribed_text: Optional[str] = None
    analysis_result: Optional[str] = None


class HealthResponse(BaseModel):
    """헬스체크 응답 모델"""
    status: str
    timestamp: str


# User Authentication 관련 모델들
class UserRegister(BaseModel):
    """회원가입 요청 모델"""
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    """로그인 요청 모델"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """토큰 응답 모델"""
    accessToken: str
    refreshToken: str
    expiresIn: int


class RefreshTokenRequest(BaseModel):
    """토큰 갱신 요청 모델"""
    refreshToken: str


class RefreshTokenResponse(BaseModel):
    """토큰 갱신 응답 모델"""
    accessToken: str
    expiresIn: int


class RegisterResponse(BaseModel):
    """회원가입 응답 모델"""
    message: str


class UserInfo(BaseModel):
    """사용자 정보 모델"""
    id: int
    email: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    
    class Config:
        from_attributes = True
