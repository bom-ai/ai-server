"""
전체 파이프라인 API 엔드포인트
"""
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.models.schemas import BatchAnalysisResponse, FileMappingValidation
from app.services.pipeline_service import pipeline_service

router = APIRouter()


@router.post("/analyze", response_model=BatchAnalysisResponse)
async def bomatic_analyze(
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
        
        # 매핑 JSON 파싱 및 검증 (이미 정규화됨)
        try:
            mapping_dict = FileMappingValidation.validate_mapping(mapping)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )
        
        # 업로드된 파일명도 동일하게 정규화
        uploaded_filenames = {
            FileMappingValidation.normalize_filename(audio.filename) 
            for audio in audios
        }
        mapping_filenames = set(mapping_dict.keys())

        # 디버깅 출력 추가
        print("=== 파일명 디버깅 ===")
        print(f"업로드된 파일명들 (정규화됨): {uploaded_filenames}")
        print(f"매핑 파일명들 (정규화됨): {mapping_filenames}")

        if uploaded_filenames != mapping_filenames:
            missing_in_mapping = uploaded_filenames - mapping_filenames
            missing_in_upload = mapping_filenames - uploaded_filenames
            error_details = []
            
            if missing_in_mapping:
                error_details.append(f"매핑에 없는 파일: {', '.join(missing_in_mapping)}")
            if missing_in_upload:
                error_details.append(f"업로드되지 않은 파일: {', '.join(missing_in_upload)}")
                
            raise HTTPException(
                status_code=400,
                detail=f"파일과 매핑이 일치하지 않습니다. {'; '.join(error_details)}"
            )
        
        # 프레임 파일 내용 읽기
        frame_content = await frame.read()
        
        # 오디오 파일들의 내용도 미리 읽기
        audio_contents = []
        for audio in audios:
            audio_content = await audio.read()
            audio_contents.append({
                'filename': FileMappingValidation.normalize_filename(audio.filename),
                'content': audio_content,
                'content_type': audio.content_type
            })
        
        # pipeline_service를 통해 배치 분석 작업 시작
        job_id = await pipeline_service.start_batch_analysis(
            frame_content, 
            audio_contents,  # UploadFile 대신 내용을 전달
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
    try:
        job_info = await pipeline_service.get_batch_status(job_id)
        
        return BatchAnalysisResponse(
            status=job_info["status"],
            message=job_info["message"],
            job_id=job_id,
            total_files=job_info["total_files"],
            processed_files=job_info["processed_files"],
            results=job_info["results"],
            errors=job_info["errors"]
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/download/{job_id}")
async def download_analysis_result(job_id: str):
    """분석 결과 파일을 다운로드합니다."""
    try:
        results = await pipeline_service.get_batch_results(job_id)
        
        return {
            "message": "파일 다운로드 준비 완료",
            "results": results["results"],
            "errors": results["errors"]
        }
    except ValueError as e:
        raise HTTPException(status_code=404 if "찾을 수 없습니다" in str(e) else 400, detail=str(e))