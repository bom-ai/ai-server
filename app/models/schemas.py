"""
Pydantic 모델 정의
"""
import json
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


class BatchAnalysisRequest(BaseModel):
    """배치 분석 요청 모델 (참조용)"""
    mapping: dict  # 오디오 파일명과 그룹명 매핑 {"파일명.mp3": "그룹명"}
    
    class Config:
        json_schema_extra = {
            "example": {
                "mapping": {
                    "interview1.mp3": "Group A", 
                    "interview2.wav": "Group B",
                    "meeting.m4a": "Group C"
                }
            }
        }


class FileMappingValidation(BaseModel):
    """파일 매핑 검증용 모델"""
    mapping: dict
    
    @classmethod
    def validate_mapping(cls, mapping_str: str) -> dict:
        """JSON 문자열 매핑을 검증하고 dict로 변환"""
        try:
            mapping_dict = json.loads(mapping_str)
            if not isinstance(mapping_dict, dict):
                raise ValueError("매핑은 객체 형태여야 합니다.")
            
            for filename, group in mapping_dict.items():
                if not isinstance(filename, str) or not isinstance(group, str):
                    raise ValueError("파일명과 그룹명은 모두 문자열이어야 합니다.")
                
                # 지원되는 오디오 파일 확장자 검증
                supported_extensions = ['.mp3', '.wav', '.m4a', '.flac', '.ogg']
                if not any(filename.lower().endswith(ext) for ext in supported_extensions):
                    raise ValueError(f"지원하지 않는 파일 형식입니다: {filename}")
            
            return mapping_dict
            
        except json.JSONDecodeError:
            raise ValueError("매핑 정보가 올바른 JSON 형식이 아닙니다.")


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


class BatchAnalysisResponse(BaseModel):
    """배치 분석 응답 모델"""
    status: str
    message: str
    job_id: str
    total_files: int
    processed_files: int = 0
    results: Optional[dict] = None  # {filename: analysis_result}
    errors: Optional[dict] = None   # {filename: error_message}


class PipelineResponse(BaseModel):
    """전체 bo:matic 파이프라인 작업 완료! -> 응답 모델"""
    message: str
    download_url: str
