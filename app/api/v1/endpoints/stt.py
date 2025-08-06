"""
STT 관련 API 엔드포인트
"""
from typing import List
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form

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


@router.post("/audio-url", response_model=STTResponse)
async def start_stt_with_audio_url(request: STTRequest, background_tasks: BackgroundTasks):
    """오디오 파일의 url (외부 스토리지에 저장된 경우) 을 받아 STT 작업을 시작합니다."""
    try:
        # STT 요청 보내기
        result = await stt_service.request_stt_with_audio_url(
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


@router.post("/file-upload", response_model=STTResponse)
async def start_stt_with_file_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="업로드할 음성 파일"),
    language: str = Form("ko", description="언어 설정 (기본값: ko)"),
    enable_speaker_diarization: bool = Form(True, description="화자 분리 활성화 여부")
):
    """파일을 직접 업로드하여 STT 작업을 시작합니다."""
    try:
        # 파일 형식 검증 (선택적)
        if not file.content_type or not file.content_type.startswith('audio/'):
            # 확장자로도 체크
            if not file.filename or not any(file.filename.lower().endswith(ext) for ext in ['.wav', '.mp3', '.m4a', '.flac', '.ogg']):
                raise HTTPException(
                    status_code=400, 
                    detail="지원하지 않는 파일 형식입니다. 음성 파일을 업로드해주세요."
                )
        
        # STT 요청 보내기 (파일 직접 업로드)
        result = await stt_service.request_stt_with_file_upload(
            file, 
            language, 
            enable_speaker_diarization
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
            message=f"파일 '{file.filename}' 음성 변환 작업이 시작되었습니다.",
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