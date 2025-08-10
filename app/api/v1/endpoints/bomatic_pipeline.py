"""
전체 파이프라인 API 엔드포인트
"""
import json
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Response

from app.models.schemas import BatchAnalysisResponse, FileMappingValidation
from app.services.pipeline_service import pipeline_service
from app.utils.docx_processor import (
    fill_frame_with_analysis_bytes,
    replace_analysis_with_parsed,
    parse_analysis_sections_any,
)

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


@router.post("/download/{job_id}")
async def download_analysis_result(job_id: str, frame: UploadFile = File(...)):
    """
    사용자로부터 DOCX 템플릿 파일을 받아, 분석 결과를 채워 다운로드합니다.
    """
    try:
        # 파일이 DOCX 형식인지 간단히 확인 (선택 사항이지만 권장)
        if not frame.filename.endswith('.docx'):
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .docx file.")

        job_info = await pipeline_service.get_batch_results(job_id)
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


@router.post("/download-test")
async def download_analysis_result_direct(
    frame: UploadFile = File(...),
    json_file: UploadFile = File(...)
):
    """
    (임시) 사용자로부터 DOCX 템플릿 파일과 job_info JSON 파일을 직접 받아
    분석 결과를 채워 다운로드합니다.
    """
    # 1. 파일 형식 확인
    if not frame.filename.endswith('.docx'):
        raise HTTPException(status_code=400, detail="The 'frame' file must be a .docx file.")
    if not json_file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="The 'json_file' must be a .json file.")

    json_content = None
    try:
        # 2. 업로드된 JSON 파일의 내용을 읽고 파싱
        json_content = await json_file.read()
        job_info = json.loads(json_content)

        # 3. 기존 로직 재사용
        parsed_job_info = replace_analysis_with_parsed(job_info)

        frame_docx_bytes = await frame.read()

        modified_docx_bytes = fill_frame_with_analysis_bytes(
            json_data=parsed_job_info,
            frame_docx_bytes=frame_docx_bytes
        )

        # 4. 파일 다운로드 응답 생성
        file_name = "direct_analysis_result.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        headers = {
            "Content-Disposition": f'attachment; filename="{file_name}"'
        }

        return Response(content=modified_docx_bytes, media_type=media_type, headers=headers)

    except json.JSONDecodeError:
        # json_content가 있을 경우 디버깅을 위해 출력
        error_detail = "Invalid JSON format in 'json_file'."
        if json_content:
            error_detail += f" Content: {json_content[:200].decode(errors='ignore')}"
        raise HTTPException(status_code=400, detail=error_detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        # 5. 업로드된 두 파일의 임시 리소스를 모두 닫아줍니다.
        await frame.close()
        await json_file.close()