"""
파이프라인 서비스 - bo:matic 애플리케이션의 전체 파이프라인 로직
"""
import asyncio
import uuid
from typing import Dict, Any, List, Optional, Literal
from google.cloud import storage

from app.services.stt_service import stt_service
from app.services.gemini_service import gemini_service
from app.core.config import settings
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
        # Cloud Storage 클라이언트 초기화
        self.storage_client = storage.Client()
        # 버킷 이름 설정에서 가져오기
        self.bucket_name = settings.gcs_bucket_name
    
    async def _cleanup_cloud_storage_file(self, audio_url: str):
        """Cloud Storage에서 임시 파일을 삭제합니다."""
        try:
            # URL에서 blob 이름 추출
            blob_name = audio_url.split(f'/{self.bucket_name}/')[1]
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            blob.delete()
        except Exception as e:
            # 파일 삭제 실패는 치명적이지 않으므로 로그만 남김
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Cloud Storage 파일 삭제 실패: {str(e)}")
    
    async def _upload_to_cloud_storage(self, audio_content: bytes, filename: str) -> str:
        """오디오 파일을 Cloud Storage에 업로드하고 공개 URL을 반환합니다."""
        try:
            # 임시 파일 경로 생성
            unique_filename = f"{uuid.uuid4()}_{filename}"
            blob_name = f"audio/{unique_filename}"
            
            # Cloud Storage에 업로드
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            
            # 파일 업로드
            blob.upload_from_string(audio_content)
            
            # 공개 읽기 권한 설정
            blob.make_public()
            
            # 공개 URL 반환
            return blob.public_url
            
        except Exception as e:
            raise Exception(f"Cloud Storage 업로드 실패: {str(e)}")
    
    async def start_batch_analysis(
        self,
        frame_content: bytes,
        audio_contents: List[dict],
        mapping: dict,
        template_type: Literal["raw", "refined"]
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
            "total_files": len(audio_contents),
            "processed_files": 0,
            "results": {},
            "errors": {}
        }
        
        # 백그라운드에서 배치 처리 작업 시작
        asyncio.create_task(self._batch_analysis_task(
            job_id, 
            frame_content, 
            audio_contents, 
            mapping,
            template_type
        ))
        
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
        
        job_completed = self.batch_jobs[job_id]
        if job_completed["status"] != "completed":
            raise ValueError("작업이 아직 완료되지 않았습니다.")
        
        return job_completed
    
    async def _batch_analysis_task(
        self, 
        job_id: str, 
        frame_content: bytes, 
        audio_contents: List[dict],
        mapping: dict,
        template_type: Literal["raw", "refined"]
    ):
        """배치 분석 작업을 백그라운드에서 처리합니다."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # 1. 프레임 파일(.docx) 처리 - custom_items 추출
            docx_table_info = extract_text_with_separated_tables(frame_content)
            structured_items = extract_table_headers_with_subitems(frame_content)
            custom_items = format_items_for_prompt(structured_items)
            
            logger.info(f"Job {job_id}: Processing {len(audio_contents)} audio files")
            
            for i, audio_data in enumerate(audio_contents):
                filename = audio_data['filename']  # dict에서 접근
                audio_content = audio_data['content']
                content_type = audio_data['content_type']
                group_name = mapping.get(filename, "Unknown Group")
                
                logger.info(f"Job {job_id}: Processing file {i+1}/{len(audio_contents)}: {filename}")
                
                try:
                    # 2. 오디오 파일을 Cloud Storage에 업로드
                    logger.info(f"Job {job_id}: Uploading {filename} to Cloud Storage")
                    audio_url = await self._upload_to_cloud_storage(audio_content, filename)
                    logger.info(f"Job {job_id}: Successfully uploaded {filename} to Cloud Storage: {audio_url}")
                    
                    # 3. STT 처리 - Cloud Storage URL 사용
                    logger.info(f"Job {job_id}: Starting STT for {filename}")
                    stt_result = await self.stt_service.request_stt_with_audio_url(
                        audio_url
                    )
                    rid = stt_result.get("rid")
                    logger.info(f"Job {job_id}: STT request ID for {filename}: {rid}")
                    
                    if rid:
                        # STT 완료까지 대기
                        logger.info(f"Job {job_id}: Waiting for STT completion for {filename}")
                        transcribed_text = await self.stt_service.wait_for_completion(rid)
                        logger.info(f"Job {job_id}: STT completed for {filename}, text length: {len(transcribed_text)}")
                        
                        # Gemini API 호출 전 대기 시간 추가 (Rate Limiting 방지)
                        if i > 0:  # 첫 번째 파일이 아닌 경우에만 대기
                            wait_time = min(5, i * 2)  # 점진적으로 대기 시간 증가 (최대 5초)
                            logger.info(f"Job {job_id}: Waiting {wait_time} seconds before Gemini API call to prevent rate limiting")
                            await asyncio.sleep(wait_time)
                        
                        # 4. Gemini API를 통한 내용 분석
                        logger.info(f"Job {job_id}: Starting Gemini analysis for {filename}")
                        analysis_result = await self.gemini_service.analyze_text(
                            text_content=transcribed_text,
                            custom_items=custom_items,
                            template_type=template_type
                        )
                        logger.info(f"Job {job_id}: Gemini analysis completed for {filename}")
                        
                        self.batch_jobs[job_id]["results"][filename] = {
                            "group": group_name,
                            "audio_url": audio_url,  # Cloud Storage URL 포함
                            "transcribed_text": transcribed_text,
                            "analysis": analysis_result
                        }
                        logger.info(f"Job {job_id}: Successfully processed {filename}")
                    else:
                        error_msg = "STT 요청 ID를 받지 못했습니다."
                        self.batch_jobs[job_id]["errors"][filename] = error_msg
                        logger.error(f"Job {job_id}: {error_msg} for {filename}")
                        
                except Exception as e:
                    error_msg = str(e)
                    self.batch_jobs[job_id]["errors"][filename] = error_msg
                    logger.error(f"Job {job_id}: Error processing {filename}: {error_msg}")
                    logger.error(f"Job {job_id}: Exception details for {filename}", exc_info=True)
            
                # 진행 상황 업데이트
                self.batch_jobs[job_id]["processed_files"] = i + 1
                logger.info(f"Job {job_id}: Progress updated: {i+1}/{len(audio_contents)}")
            
            # 작업 완료
            self.batch_jobs[job_id]["status"] = "completed"
            self.batch_jobs[job_id]["message"] = "배치 분석 작업이 완료되었습니다."
            
            # Cloud Storage 임시 파일 정리
            logger.info(f"Job {job_id}: Starting cleanup of Cloud Storage files")
            for filename, result in self.batch_jobs[job_id]["results"].items():
                if "audio_url" in result:
                    await self._cleanup_cloud_storage_file(result["audio_url"])
            logger.info(f"Job {job_id}: Cloud Storage cleanup completed")
            
        except Exception as e:
            self.batch_jobs[job_id]["status"] = "failed"
            self.batch_jobs[job_id]["message"] = f"배치 분석 중 오류 발생: {str(e)}"
            logger.error(f"Job {job_id}: Batch analysis failed: {str(e)}", exc_info=True)


# bo:matic 파이프라인 서비스 인스턴스
pipeline_service = PipelineService()
