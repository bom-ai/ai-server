"""
STT 관련 API 엔드포인트
"""
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.models.schemas import STTRequest, STTResponse
from app.services.stt_service import stt_service

router = APIRouter()

# STT 작업 저장소 (실제 운영에서는 Redis 등 사용 권장)
stt_jobs = {}


async def background_stt_task(rid: str):
    """백그라운드에서 STT 작업을 처리합니다."""
    stt_jobs[rid] = {
        "status": "processing", 
        "message": "음성 변환 중...", 
        "result": None
    }
    
    try:
        result = await stt_service.wait_for_completion(rid)
        stt_jobs[rid] = {
            "status": "completed", 
            "message": "변환 완료", 
            "result": result
        }
    except HTTPException as e:
        stt_jobs[rid] = {
            "status": "failed", 
            "message": f"변환 실패: {e.detail}", 
            "result": None
        }
    except Exception as e:
        stt_jobs[rid] = {
            "status": "failed", 
            "message": f"처리 중 오류: {str(e)}", 
            "result": None
        }


@router.post("/start", response_model=STTResponse)
async def start_stt(request: STTRequest, background_tasks: BackgroundTasks):
    """음성을 텍스트로 변환하는 작업을 시작합니다."""
    try:
        # STT 요청 보내기
        result = await stt_service.request_stt(
            request.audio_url, 
            request.language, 
            request.enable_speaker_diarization
        )
        
        rid = result.get("rid")
        if not rid:
            raise HTTPException(
                status_code=500, 
                detail="STT 요청 ID를 받지 못했습니다."
            )
        
        # 백그라운드에서 STT 작업 처리
        background_tasks.add_task(background_stt_task, rid)
        
        return STTResponse(
            status="started",
            message="음성 변환 작업이 시작되었습니다.",
            rid=rid
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{rid}", response_model=STTResponse)
async def get_stt_status(rid: str):
    """STT 작업 상태를 확인합니다."""
    if rid not in stt_jobs:
        raise HTTPException(
            status_code=404, 
            detail="해당 작업을 찾을 수 없습니다."
        )
    
    job = stt_jobs[rid]
    return STTResponse(
        status=job["status"],
        message=job["message"],
        rid=rid,
        transcribed_text=job["result"]
    )


@router.delete("/jobs/{rid}")
async def delete_stt_job(rid: str):
    """완료된 STT 작업을 삭제합니다."""
    if rid in stt_jobs:
        del stt_jobs[rid]
        return {"message": f"작업 {rid}가 삭제되었습니다."}
    else:
        raise HTTPException(
            status_code=404, 
            detail="해당 작업을 찾을 수 없습니다."
        )
