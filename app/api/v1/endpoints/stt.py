"""
STT 관련 API 엔드포인트
"""
import asyncio
import json
import uuid
from typing import List
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form

from app.models.schemas import STTRequest, STTResponse, BatchAnalysisResponse
from app.services.stt_service import stt_service
from app.services.analysis_service import analysis_service
from app.services.gemini_service import gemini_service
from app.utils.docx_processor import extract_text_from_docx

router = APIRouter()

# STT 작업 저장소 (실제 운영에서는 Redis 등 사용 권장)
stt_jobs = {}
batch_jobs = {}  # 배치 작업 저장소


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


@router.post("/upload", response_model=STTResponse)
async def upload_and_start_stt(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="업로드할 음성 파일"),
    language: str = Form("ko", description="언어 설정 (기본값: ko)"),
    enable_speaker_diarization: bool = Form(True, description="화자 분리 활성화 여부")
):
    """파일을 직접 업로드하여 음성을 텍스트로 변환하는 작업을 시작합니다."""
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
        result = await stt_service.request_stt_with_file(
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


async def batch_analysis_task(job_id: str, frame_content: bytes, audio_files: List[UploadFile], mapping: dict):
    """배치 분석 작업을 백그라운드에서 처리합니다."""
    batch_jobs[job_id] = {
        "status": "processing",
        "message": "배치 분석 작업 진행 중...",
        "total_files": len(audio_files),
        "processed_files": 0,
        "results": {},
        "errors": {}
    }
    
    try:
        # 1. 프레임 파일(.docx) 처리
        frame_text = extract_text_from_docx(frame_content)
        
        for i, audio_file in enumerate(audio_files):
            filename = audio_file.filename
            group_name = mapping.get(filename, "Unknown Group")
            
            try:
                # 2. STT 처리
                stt_result = await stt_service.request_stt_with_file(audio_file)
                rid = stt_result.get("rid")
                
                if rid:
                    # STT 완료까지 대기
                    transcribed_text = await stt_service.wait_for_completion(rid)
                    
                    # 3. Gemini API를 통한 내용 분석
                    analysis_prompt = f"""
                    프레임 내용: {frame_text}
                    그룹명: {group_name}
                    녹음 내용: {transcribed_text}
                    
                    위 내용을 바탕으로 분석을 수행해주세요.
                    """
                    
                    analysis_result = await gemini_service.analyze_text(analysis_prompt) 
                    # custom_items에 해당하는 리스트 추가해줘야 함 
                    # docx_processor에 기능 추가해서 처리할 필요 o
                    
                    batch_jobs[job_id]["results"][filename] = {
                        "group": group_name,
                        "transcribed_text": transcribed_text,
                        "analysis": analysis_result
                    }
                else:
                    batch_jobs[job_id]["errors"][filename] = "STT 요청 ID를 받지 못했습니다."
                    
            except Exception as e:
                batch_jobs[job_id]["errors"][filename] = str(e)
            
            # 진행 상황 업데이트
            batch_jobs[job_id]["processed_files"] = i + 1
        
        # 작업 완료
        batch_jobs[job_id]["status"] = "completed"
        batch_jobs[job_id]["message"] = "배치 분석 작업이 완료되었습니다."
        
    except Exception as e:
        batch_jobs[job_id]["status"] = "failed"
        batch_jobs[job_id]["message"] = f"배치 분석 중 오류 발생: {str(e)}"


@router.post("/batch-analysis", response_model=BatchAnalysisResponse)
async def batch_analysis(
    background_tasks: BackgroundTasks,
    frame: UploadFile = File(..., description="분석 프레임 (.docx 파일)"),
    audios: List[UploadFile] = File(..., description="오디오 파일들 (.mp3 등)"),
    mapping: str = Form(..., description="오디오 파일과 그룹명 매핑 (JSON 문자열)")
):
    """
    여러 오디오 파일과 프레임을 한 번에 업로드하여 배치 분석을 수행합니다.
    
    - frame: 분석 틀이 되는 .docx 파일
    - audios: 여러 개의 오디오 파일 (.mp3, .wav 등)
    - mapping: {"파일명.mp3": "그룹명"} 형태의 JSON 문자열
    """
    try:
        # 프레임 파일 검증
        if not frame.filename or not frame.filename.lower().endswith('.docx'):
            raise HTTPException(
                status_code=400,
                detail="프레임 파일은 .docx 형식이어야 합니다."
            )
        
        # 오디오 파일 검증
        for audio in audios:
            if not audio.filename or not any(audio.filename.lower().endswith(ext) for ext in ['.mp3', '.wav', '.m4a', '.flac', '.ogg']):
                raise HTTPException(
                    status_code=400,
                    detail=f"지원하지 않는 파일 형식입니다: {audio.filename}"
                )
        
        # 매핑 JSON 파싱
        try:
            mapping_dict = json.loads(mapping)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="매핑 정보가 올바른 JSON 형식이 아닙니다."
            )
        
        # 작업 ID 생성
        job_id = str(uuid.uuid4())
        
        # 프레임 파일 내용 읽기
        frame_content = await frame.read()
        
        # 백그라운드에서 배치 분석 작업 시작
        background_tasks.add_task(
            batch_analysis_task, 
            job_id, 
            frame_content, 
            audios, 
            mapping_dict
        )
        
        return BatchAnalysisResponse(
            status="started",
            message="배치 분석 작업이 시작되었습니다.",
            job_id=job_id,
            total_files=len(audios)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-status/{job_id}", response_model=BatchAnalysisResponse)
async def get_batch_status(job_id: str):
    """배치 분석 작업 상태를 확인합니다."""
    if job_id not in batch_jobs:
        raise HTTPException(
            status_code=404,
            detail="해당 작업을 찾을 수 없습니다."
        )
    
    job = batch_jobs[job_id]
    return BatchAnalysisResponse(
        status=job["status"],
        message=job["message"],
        job_id=job_id,
        total_files=job["total_files"],
        processed_files=job["processed_files"],
        results=job["results"],
        errors=job["errors"]
    )
