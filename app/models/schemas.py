"""
Pydantic 모델 정의
"""
from pydantic import BaseModel
from typing import Optional


class STTRequest(BaseModel):
    """STT 요청 모델"""
    audio_url: str                      # 음성 파일 URL
    language: str = "ko"                # 언어 설정
    enable_speaker_diarization: bool    # 화자 분리 기능


class AnalysisRequest(BaseModel):
    """텍스트 분석 요청 모델"""
    text_content: str                   # 분석할 텍스트
    analysis_type: str = "phase1"       # 분석 단계 (phase1 or phase2)


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
