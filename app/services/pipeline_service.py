"""
파이프라인 서비스 - bo:matic 애플리케이션의 전체 파이프라인 로직
"""
import asyncio
import uuid
from typing import Dict, Any, List, Optional
from fastapi import UploadFile

from app.services.stt_service import stt_service
from app.services.gemini_service import gemini_service
from app.utils.docx_processor import (
    extract_text_with_separated_tables, 
    extract_table_headers_with_subitems,
    format_items_for_prompt
)


class PipelineService:
    """bo:matic 파이프라인 서비스"""
    
    def __init__(self):
        self.stt_service = stt_service
        self.gemini_service = gemini_service
        # 배치 작업 저장소
        self.batch_jobs = {}
    
    async def bomatic_pipeline(
        self,
        audio_url: str,
        language: str = "ko",
        enable_speaker_diarization: bool = True,
        custom_items: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """음성 변환부터 텍스트 분석까지 전체 파이프라인을 실행합니다."""
        
        # 1단계: STT 요청
        stt_result = await self.stt_service.request_stt(
            audio_url, language, enable_speaker_diarization
        )
        rid = stt_result.get("rid")
        
        if not rid:
            raise ValueError("STT 요청 ID를 받지 못했습니다.")
        
        # 2단계: STT 완료까지 대기
        transcribed_text = await self.stt_service.wait_for_completion(rid)
        
        # 3단계: Gemini 분석 (커스텀 Items 전달)
        analysis_result = await self.gemini_service.analyze_text(
            transcribed_text, custom_items
        )
        
        return {
            "stt_rid": rid,
            "transcribed_text": transcribed_text,
            "analysis_result": analysis_result
        }
    
    async def analyze_text_with_custom_prompt(
        self,
        text_content: str,
        system_prompt: str
    ) -> str:
        """커스텀 시스템 프롬프트를 사용하여 텍스트를 분석합니다."""
        
        # Gemini 서비스에 커스텀 프롬프트로 분석 요청
        analysis_result = await self.gemini_service.analyze_with_custom_prompt(
            text_content, system_prompt
        )
        
        return analysis_result
    
    async def start_batch_analysis(
        self,
        frame_content: bytes,
        audio_files: List[UploadFile],
        mapping: dict
    ) -> str:
        """배치 분석 작업을 시작하고 job_id를 반환합니다."""
        
        # 작업 ID 생성
        job_id = str(uuid.uuid4())
        
        try:
            # 1. DOCX 파일 처리 테스트
            docx_table_info = extract_text_with_separated_tables(frame_content)
            structured_items = extract_table_headers_with_subitems(frame_content)
            custom_items = format_items_for_prompt(structured_items)
            
            print(f"DOCX 처리 완료: {len(custom_items)}개 항목 추출")
            
        except Exception as e:
            print(f"DOCX 처리 실패: {str(e)}")
            raise Exception(f"프레임 파일 처리 실패: {str(e)}")
        
        # 배치 작업 정보 초기화
        self.batch_jobs[job_id] = {
            "status": "processing",
            "message": "배치 분석 작업 진행 중...",
            "total_files": len(audio_files),
            "processed_files": 0,
            "results": {},
            "errors": {}
        }
        
        # 백그라운드에서 배치 처리 작업 시작
        asyncio.create_task(self._batch_analysis_task(job_id, frame_content, audio_files, mapping))
        
        return job_id
    
    async def get_batch_status(self, job_id: str) -> Dict[str, Any]:
        """배치 분석 작업 상태를 확인합니다."""
        if job_id not in self.batch_jobs:
            raise ValueError("해당 작업을 찾을 수 없습니다.")
        
        return self.batch_jobs[job_id]
    
    async def get_batch_results(self, job_id: str) -> Dict[str, Any]:
        """완료된 배치 분석 결과를 반환합니다."""
        if job_id not in self.batch_jobs:
            raise ValueError("해당 작업을 찾을 수 없습니다.")
        
        job = self.batch_jobs[job_id]
        if job["status"] != "completed":
            raise ValueError("작업이 아직 완료되지 않았습니다.")
        
        return {
            "results": job["results"],
            "errors": job.get("errors", {})
        }
    
    async def _batch_analysis_task(
        self, 
        job_id: str, 
        frame_content: bytes, 
        audio_files: List[UploadFile], 
        mapping: dict
    ):
        """배치 분석 작업을 백그라운드에서 처리합니다."""
        try:
            # 1. 프레임 파일(.docx) 처리 - custom_items 추출
            docx_table_info = extract_text_with_separated_tables(frame_content)
            structured_items = extract_table_headers_with_subitems(frame_content)
            custom_items = format_items_for_prompt(structured_items)
            
            for i, audio_file in enumerate(audio_files):
                filename = audio_file.filename
                group_name = mapping.get(filename, "Unknown Group")
                
                try:
                    # 2. STT 처리
                    stt_result = await self.stt_service.request_stt_with_file_upload(audio_file)
                    rid = stt_result.get("rid")
                    
                    if rid:
                        # STT 완료까지 대기
                        transcribed_text = await self.stt_service.wait_for_completion(rid)
                        
                        # 3. Gemini API를 통한 내용 분석
                        analysis_result = await self.gemini_service.analyze_text_with_items(
                            text_content=transcribed_text,
                            custom_items=custom_items
                        )
                        
                        self.batch_jobs[job_id]["results"][filename] = {
                            "group": group_name,
                            "transcribed_text": transcribed_text,
                            "analysis": analysis_result
                        }
                    else:
                        self.batch_jobs[job_id]["errors"][filename] = "STT 요청 ID를 받지 못했습니다."
                        
                except Exception as e:
                    self.batch_jobs[job_id]["errors"][filename] = str(e)
                
                # 진행 상황 업데이트
                self.batch_jobs[job_id]["processed_files"] = i + 1
            
            # 작업 완료
            self.batch_jobs[job_id]["status"] = "completed"
            self.batch_jobs[job_id]["message"] = "배치 분석 작업이 완료되었습니다."
            
        except Exception as e:
            self.batch_jobs[job_id]["status"] = "failed"
            self.batch_jobs[job_id]["message"] = f"배치 분석 중 오류 발생: {str(e)}"


# bo:matic 파이프라인 서비스 인스턴스
pipeline_service = PipelineService()
