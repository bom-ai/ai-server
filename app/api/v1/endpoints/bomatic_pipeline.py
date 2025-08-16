"""
전체 파이프라인 API 엔드포인트
"""
import json
from typing import List, Literal
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Response, Query, Depends

from app.models.schemas import BatchAnalysisResponse, FileMappingValidation
from app.services.pipeline_service import pipeline_service
from app.api.deps import get_current_user  # 별도 deps 파일에서 import
from app.utils.docx_processor import (
    fill_frame_with_analysis_bytes,
    replace_analysis_with_parsed,
)

router = APIRouter()

@router.post("/request-analysis")
async def request_analysis(
    # 각 필드를 개별 Form 데이터로 받습니다.
    filenames: List[str] = Form(..., description="업로드할 오디오 파일명 목록"),
    mapping: str = Form(..., description="{'파일명': '그룹명'} 형태의 JSON 문자열"),
    template_type: str = Form("refined", description="분석 템플릿 타입 ('raw' 또는 'refined')"),
    frame: UploadFile = File(..., description="분석 프레임 (.docx 파일)"),
    current_user: dict = Depends(get_current_user)
):
    """
    배치 분석 작업을 요청하고, 파일들을 직접 업로드할 서명된 URL들을 발급받습니다.
    """
    # 1. 입력 값 유효성 검사
    if not frame.filename or not frame.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="프레임 파일은 .docx 형식이어야 합니다.")

    if template_type not in ["raw", "refined"]:
        raise HTTPException(status_code=400, detail="template_type은 'raw' 또는 'refined'만 가능합니다.")

    try:
        mapping_dict = json.loads(mapping)
        if not isinstance(mapping_dict, dict):
            raise ValueError("매핑 데이터는 딕셔너리(JSON 객체) 형태여야 합니다.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="매핑(mapping) 데이터가 올바른 JSON 형식이 아닙니다.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        frame_content = await frame.read()

        result = await pipeline_service.request_batch_analysis_job(
            frame_content=frame_content,
            filenames=filenames,
            mapping=mapping_dict,
            template_type=template_type,
        )
        return result
        
    except Exception as e:
        print(f"Request analysis error: {e}")
        raise HTTPException(status_code=500, detail=f"서버 내부 오류가 발생했습니다: {e}")

@router.post("/start-analysis/{job_id}", response_model=BatchAnalysisResponse)
async def start_analysis(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    클라이언트가 GCS로 파일 업로드를 완료한 후, 실제 분석 작업을 시작하도록 지시합니다.
    """
    try:
        await pipeline_service.start_batch_analysis(job_id)
        job_info = await pipeline_service.get_batch_status(job_id)

        return BatchAnalysisResponse(
            status=job_info["status"],
            message="배치 분석 작업이 시작되었습니다.",
            job_id=job_id,
            total_files=job_info["total_files"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze", response_model=BatchAnalysisResponse)
async def bomatic_analyze(
    frame: UploadFile = File(..., description="분석 프레임 (.docx 파일)"),
    audios: List[UploadFile] = File(..., description="오디오 파일들 (.mp3 등)"),
    mapping: str = Form(..., description="오디오 파일과 그룹명 매핑 (JSON 문자열)"),
    template_type: Literal["raw", "refined"] = Query(
        "refined",
        description="분석에 사용할 프롬프트 템플릿 ('raw' 또는 'refined')"
    ),
    current_user = Depends(get_current_user)  # 인증 의존성 추가
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
        
        # pipeline_service를 통해 배치 분석 작업 시작 (사용자 ID 포함)
        job_id = await pipeline_service.start_batch_analysis(
            frame_content, 
            audio_contents,  # UploadFile 대신 내용을 전달
            mapping_dict,
            template_type,
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
async def get_batch_status(
    job_id: str,
    current_user = Depends(get_current_user)  # 인증 의존성 추가
):
    """배치 분석 작업 상태를 확인합니다."""
    try:
        job_info = await pipeline_service.get_batch_status(
            job_id, 
        )
        
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


@router.post("/download/{job_id}")
async def download_analysis_result(
    job_id: str, 
    frame: UploadFile = File(...),
    current_user = Depends(get_current_user)  # 인증 의존성 추가
):
    """
    사용자로부터 DOCX 템플릿 파일을 받아, 분석 결과를 채워 다운로드합니다.
    """
    try:
        # 파일이 DOCX 형식인지 간단히 확인 (선택 사항이지만 권장)
        if not frame.filename.endswith('.docx'):
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .docx file.")

        job_info = await pipeline_service.get_batch_results(
            job_id,
        )
        
        parsed_job_info = replace_analysis_with_parsed(job_info)

        frame_docx_bytes = await frame.read()

        modified_docx_bytes = fill_frame_with_analysis_bytes(
            json_data=parsed_job_info,
            frame_docx_bytes=frame_docx_bytes
        )

        file_name = f"analysis_result_{job_id}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        headers = {
            "Content-Disposition": f'attachment; filename="{file_name}"'
        }

        return Response(content=modified_docx_bytes, media_type=media_type, headers=headers)

    except ValueError as e:
        raise HTTPException(status_code=404 if "찾을 수 없습니다" in str(e) else 400, detail=str(e))
    finally:
        # 업로드된 파일의 임시 리소스를 닫아줍니다.
        await frame.close()

