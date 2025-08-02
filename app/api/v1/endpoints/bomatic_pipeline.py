"""
전체 파이프라인 API 엔드포인트
"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import PipelineResponse
from app.services.analysis_service import analysis_service

router = APIRouter()


@router.post("/full-analysis", response_model=PipelineResponse)
async def full_analysis_pipeline(
    audio_url: str,
    language: str = "ko",
    enable_speaker_diarization: bool = True,
    analysis_type: str = "phase1"
):
    """음성 변환부터 텍스트 분석까지 전체 파이프라인을 실행합니다."""
    try:
        result = await analysis_service.bomatic_pipeline(
            audio_url=audio_url,
            language=language,
            enable_speaker_diarization=enable_speaker_diarization,
            analysis_type=analysis_type
        )
        
        return PipelineResponse(
            status="completed",
            message="전체 파이프라인이 완료되었습니다.",
            stt_rid=result["stt_rid"],
            transcribed_text=result["transcribed_text"],
            analysis_result=result["analysis_result"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
