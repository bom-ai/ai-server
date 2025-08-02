"""
전체 파이프라인 API 엔드포인트
"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import PipelineResponse, PipelineRequest
from app.services.analysis_service import analysis_service

router = APIRouter()


@router.post("/full-analysis", response_model=PipelineResponse)
async def full_analysis_pipeline(request: PipelineRequest):
    """음성 변환부터 텍스트 분석까지 전체 파이프라인을 실행합니다."""
    try:
        result = await analysis_service.bomatic_pipeline(
            audio_url=request.audio_url,
            language=request.language,
            enable_speaker_diarization=request.enable_speaker_diarization,
            custom_items=request.custom_items
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
